# GitLab Copilot Coding Agent 部署指南

本文档详细记录了在 Kubernetes 环境中部署 GitLab Copilot Coding Agent 的完整步骤。

## 架构概览

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  App Repository (你的应用代码仓库)                                            │
│  ├── 创建 Issue 分配给 Copilot → 触发自动编码                                  │
│  ├── MR 中 @copilot-agent → 触发代码修改                                      │
│  └── 分配 Copilot 为 MR Reviewer → 触发代码审查                               │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼ Webhook
┌─────────────────────────────────────────────────────────────────────────────┐
│  Webhook Service (K8s 部署)                                                  │
│  ├── 接收 GitLab Webhook 事件                                                │
│  ├── 解析事件并触发 Pipeline                                                  │
│  └── URL: https://your-webhook-domain.com/webhook                           │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼ Trigger Pipeline
┌─────────────────────────────────────────────────────────────────────────────┐
│  Copilot Coding Agent Repository                                             │
│  ├── 运行 CI/CD Pipeline                                                     │
│  ├── 使用 Copilot CLI 生成代码                                                │
│  └── 推送代码到 App Repository                                               │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 第一部分：Copilot Coding Agent 仓库配置

### 1. 创建 Copilot Bot 用户

| 步骤 | 操作 |
|------|------|
| 1 | 在 GitLab 创建新账户（如 `gh-copilot` 或 `copilot-agent`） |
| 2 | 进入 User Settings → Personal Access Tokens |
| 3 | 创建 Token，勾选所有权限（至少需要 `api`, `read_repository`, `write_repository`） |
| 4 | 记录用户名和 Token |

### 2. 导入 Coding Agent 仓库

1. 登录 GitLab，点击 **New Project**
2. 选择 **Import project** → **Repository by URL**
3. 填写：
   - Git repository URL: `https://github.com/satomic/gitlab-copilot-coding-agent.git`
   - Project name: 自定义（如 `copilot-coding-agent`）
   - Visibility Level: **Internal**（推荐）
4. 点击 **Create project**

### 3. 配置 CI/CD Variables

进入仓库 **Settings → CI/CD → Variables**，添加以下变量：

| 变量名 | 值 | Protected | Masked |
|--------|---|-----------|--------|
| `GITLAB_TOKEN` | Copilot 用户的 GitLab PAT | ❌ **取消勾选** | ✅ |
| `GITHUB_TOKEN` | GitHub Fine-grained PAT（需 Copilot 权限）| ❌ **取消勾选** | ✅ |

> ⚠️ **重要**：必须取消 Protected 选项，否则变量只在 protected branches 上可用！

#### 生成 GITHUB_TOKEN

1. 访问 https://github.com/settings/personal-access-tokens/new
2. 选择 **Fine-grained personal access tokens**
3. 填写 Token 名称和过期时间
4. 在 **Account permissions** 中：
   - 找到 **GitHub Copilot**
   - 设置为 **Read and write** ✅
5. 点击 **Generate token**
6. 复制并保存 Token

> **前提条件**：生成 Token 的 GitHub 账户必须有有效的 GitHub Copilot 订阅。

### 4. 配置 Pipeline Variables 权限

进入 **Settings → CI/CD**，展开 **General pipelines** 部分：

- 找到 "Minimum role required to set, update, or delete project-level pipeline variables"
- 修改为 **Developer**

### 5. 生成 Pipeline Trigger Token

进入 **Settings → CI/CD → Pipeline trigger tokens**：

1. 点击 **Add new token**
2. 填写描述（如 `webhook-trigger`）
3. 点击 **Create pipeline trigger token**
4. **记录生成的 Token**（后续 Webhook Service 需要）

### 6. 记录 Project ID

进入 **Settings → General**：

- 在页面顶部找到 **Project ID**
- **记录此 ID**（后续 Webhook Service 需要）

---

## 第二部分：K8s Runner 部署

### 1. 获取 Runner Registration Token

进入 Coding Agent 仓库 **Settings → CI/CD → Runners**：

1. 点击 **New project runner**
2. 配置选项（可选）：
   - Tags: `k8s,docker,copilot`
   - Run untagged jobs: ✅
3. 点击 **Create runner**
4. **复制显示的 Registration Token**

### 2. 配置 Runner 部署文件

进入 `k8s-runner/` 目录：

#### 编辑 `secret.yaml`

```yaml
stringData:
  runner-registration-token: "YOUR_RUNNER_REGISTRATION_TOKEN"
```

#### 编辑 `deployment.yaml`（如果不是 gitlab.com）

```yaml
- name: GITLAB_URL
  value: "https://your-gitlab.example.com"
```

### 3. 部署 Runner

```bash
cd k8s-runner/
chmod +x deploy.sh
./deploy.sh https://gitlab.com YOUR_RUNNER_TOKEN
```

或手动部署：

```bash
kubectl apply -f namespace.yaml
kubectl apply -f rbac.yaml
kubectl apply -f secret.yaml
kubectl apply -f configmap.yaml
kubectl apply -f deployment.yaml
```

### 4. 验证 Runner

```bash
# 查看 Pod 状态
kubectl -n gitlab-runner get pods -l app=gitlab-runner

# 查看日志，确认注册成功
kubectl -n gitlab-runner logs -l app=gitlab-runner
```

看到以下日志表示成功：
```
Runner registered successfully. Feel free to start it...
Configuration loaded
```

在 GitLab 仓库 **Settings → CI/CD → Runners** 中应该能看到 Runner 状态为 **online**。

---

## 第三部分：Webhook Service 部署

### 1. 配置 ConfigMap

编辑 `k8s-runner/webhook-configmap.yaml`：

```yaml
data:
  # Copilot Coding Agent 仓库的 Project ID
  PIPELINE_PROJECT_ID: "YOUR_PROJECT_ID"
  
  # 触发 Pipeline 的分支
  PIPELINE_REF: "main"
  
  # GitLab API 地址
  GITLAB_API_BASE: "https://gitlab.com"
  
  # Copilot 用户的 GitLab 用户名
  COPILOT_AGENT_USERNAME: "gh-copilot"
  
  # Git 提交时使用的邮箱
  COPILOT_AGENT_COMMIT_EMAIL: "copilot@github.com"
  
  # 监听端口
  LISTEN_HOST: "0.0.0.0"
  LISTEN_PORT: "8080"
  
  # 是否启用内联代码审查评论
  ENABLE_INLINE_REVIEW_COMMENTS: "true"
  
  # Copilot 语言 (en, zh, ja, ko, hi, th)
  COPILOT_LANGUAGE: "en"
```

### 2. 配置 Secret

编辑 `k8s-runner/webhook-secret.yaml`：

```yaml
stringData:
  # Pipeline Trigger Token（第一部分 Step 5 生成的）
  PIPELINE_TRIGGER_TOKEN: "YOUR_PIPELINE_TRIGGER_TOKEN"
  
  # Webhook 密钥（可选）
  WEBHOOK_SECRET_TOKEN: ""
```

### 3. 配置 Ingress

编辑 `k8s-runner/webhook-deployment.yaml` 中的 Ingress 部分：

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: webhook-service-ingress
  namespace: gitlab-runner
  annotations:
    cert-manager.io/issuer: letsencrypt-prod  # 根据你的环境调整
spec:
  ingressClassName: nginx  # 根据你的环境调整
  rules:
    - host: your-webhook-domain.com  # 你的域名
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: webhook-service
                port:
                  number: 8080
  tls:
    - hosts:
        - your-webhook-domain.com
      secretName: webhook-tls
```

### 4. 部署 Webhook Service

```bash
chmod +x deploy-webhook.sh
./deploy-webhook.sh YOUR_PIPELINE_TRIGGER_TOKEN
```

或手动部署：

```bash
kubectl apply -f webhook-secret.yaml
kubectl apply -f webhook-configmap.yaml
kubectl apply -f webhook-deployment.yaml
```

### 5. 验证部署

```bash
# 查看 Pod 状态
kubectl -n gitlab-runner get pods -l app=webhook-service

# 查看 Ingress
kubectl -n gitlab-runner get ingress

# 查看日志
kubectl -n gitlab-runner logs -f -l app=webhook-service
```

---

## 第四部分：App Repository 配置

### 1. 添加 Copilot 用户为成员

进入 App 仓库 **Settings → Members**：

1. 点击 **Invite members**
2. 搜索并选择 Copilot 用户（如 `gh-copilot`）
3. 选择角色：**Developer** 或 **Maintainer**
4. 点击 **Invite**

### 2. 配置 Webhook

进入 App 仓库 **Settings → Webhooks**：

1. 点击 **Add new webhook**
2. 填写配置：

| 配置项 | 值 |
|--------|---|
| URL | `https://your-webhook-domain.com/webhook` |
| Secret Token | 留空（或与 webhook-secret.yaml 中 WEBHOOK_SECRET_TOKEN 一致）|
| Trigger | ✅ Issues events |
|  | ✅ Comments |
|  | ✅ Merge request events |

3. 点击 **Add webhook**

### 3. 测试 Webhook

1. 在 Webhook 列表中找到刚创建的 Webhook
2. 点击 **Test** → **Issue events**
3. 确认返回 **HTTP 200** 或 **HTTP 202**

---

## 第五部分：使用方式

### 1. Issue 自动编码

1. 在 App 仓库创建 Issue，详细描述需求
2. 将 Issue 的 **Assignee** 设为 Copilot 用户
3. Copilot 会自动：
   - 回复确认消息
   - 分析需求并生成 TODO 计划
   - 创建 Merge Request
   - 实现代码
   - 推送代码并更新 Issue

### 2. MR 代码修改

在已有的 MR 中，添加评论（需 @ 提及 Copilot 用户）：

```
@gh-copilot 添加单元测试
@gh-copilot 修复第 45 行的空指针异常
@gh-copilot 重构用户服务，使用依赖注入
```

### 3. MR 代码审查

1. 打开 MR 页面
2. 在右侧 **Reviewers** 中添加 Copilot 用户
3. Copilot 会自动进行代码审查并发布审查报告

---

## 常用命令

```bash
# 查看所有相关 Pod
kubectl -n gitlab-runner get pods

# 查看 Runner 日志
kubectl -n gitlab-runner logs -f -l app=gitlab-runner

# 查看 Webhook Service 日志
kubectl -n gitlab-runner logs -f -l app=webhook-service

# 重启 Runner
kubectl -n gitlab-runner rollout restart deployment/gitlab-runner

# 重启 Webhook Service
kubectl -n gitlab-runner rollout restart deployment/webhook-service

# 查看 Ingress 状态
kubectl -n gitlab-runner get ingress

# 删除所有资源
kubectl delete namespace gitlab-runner
```

---

## 故障排查

### Webhook 返回 4xx 错误

1. 检查 Webhook Service 日志：
   ```bash
   kubectl -n gitlab-runner logs -l app=webhook-service
   ```
2. 确认 `PIPELINE_TRIGGER_TOKEN` 配置正确
3. 确认 `PIPELINE_PROJECT_ID` 配置正确

### Pipeline 权限错误

错误信息：`Insufficient permissions to set pipeline variables`

解决方法：
- 进入 Coding Agent 仓库 **Settings → CI/CD → General pipelines**
- 将 "Minimum role required..." 改为 **Developer**

### Copilot CLI 失败

1. 确认 `GITHUB_TOKEN` 已正确配置
2. 确认 Token 有 **Copilot** 权限
3. 确认 GitHub 账户有有效的 Copilot 订阅

验证 Token：
```bash
curl -s -H "Authorization: Bearer YOUR_GITHUB_TOKEN" \
  https://api.github.com/copilot_internal/v2/token
```

如果返回 403，说明 Token 缺少 Copilot 权限。

### Runner 未接收到 Job

1. 检查 Runner 是否在线：**Settings → CI/CD → Runners**
2. 检查 `.gitlab-ci.yml` 中的 tags 是否与 Runner 匹配
3. 查看 Runner 日志确认是否有错误

---

## 部署清单

| 组件 | 检查项 |
|------|--------|
| Copilot Bot 用户 | ☐ 已创建 GitLab 用户 |
|  | ☐ 已生成 GitLab PAT |
| Coding Agent 仓库 | ☐ 已导入仓库 |
|  | ☐ 已配置 GITLAB_TOKEN 变量 |
|  | ☐ 已配置 GITHUB_TOKEN 变量（带 Copilot 权限）|
|  | ☐ 已修改 Pipeline 变量权限 |
|  | ☐ 已生成 Pipeline Trigger Token |
|  | ☐ 已记录 Project ID |
| K8s Runner | ☐ 已部署到 K8s |
|  | ☐ Runner 状态为 online |
| Webhook Service | ☐ 已部署到 K8s |
|  | ☐ Ingress 配置正确 |
|  | ☐ 可通过公网访问 |
| App Repository | ☐ 已添加 Copilot 用户为成员 |
|  | ☐ 已配置 Webhook |
|  | ☐ Webhook 测试返回 200/202 |

---

## 相关文件

```
k8s-runner/
├── deploy.sh              # Runner 一键部署脚本
├── deploy-webhook.sh      # Webhook Service 一键部署脚本
├── namespace.yaml         # Namespace 定义
├── rbac.yaml              # RBAC 权限配置
├── secret.yaml            # Runner Token
├── configmap.yaml         # Runner 配置
├── deployment.yaml        # Runner Deployment
├── webhook-secret.yaml    # Webhook Service Secret
├── webhook-configmap.yaml # Webhook Service ConfigMap
├── webhook-deployment.yaml # Webhook Service Deployment + Service + Ingress
└── README.md              # K8s 部署说明
```
