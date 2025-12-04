docs/DEPLOYMENT_GUIDE_CN.md 有这个项目的统一描述

可以通过 kubectl 去替换 service hook 或gitlab runner 的 deployment , 这里有个例子：
```
kubectl set image deployment/webhook-service webhook-service=nikadwang.azurecr.io/webhook-service:debug -n gitlab-runner && kubectl rollout status deployment/webhook-service -n gitlab-runner
```