# 零成本演示部署

本方案在 Render 的一个 Docker Web Service 中同时运行 FastAPI 与 React 构建产物。队友通过同一个 HTTPS 地址访问页面、上传材料和调用 API，不依赖开发者电脑在线。

[打开 Render 部署入口](https://render.com/deploy?repo=https%3A%2F%2Fgithub.com%2FlWinsonl%2FYanzheng-ExperimentGuard)

## 部署配置

仓库根目录的 `render.yaml` 固定使用 `plan: free`，不创建数据库、持久化磁盘或其他付费资源。Docker 构建时先安装前端依赖并生成 `dist`，再将产物复制到 Python 镜像。

生产进程通过 `backend/start_server.py` 启动，监听 `0.0.0.0` 和 `PORT` 指定的端口；仅使用一个 worker，与当前内存及 JSON 会话存储方式保持一致。

| 设置 | 值 |
| --- | --- |
| 仓库 | `lWinsonl/Yanzheng-ExperimentGuard` |
| 分支 | `main` |
| 服务类型 | Web Service |
| 运行方式 | Docker，仓库根目录的 `Dockerfile` |
| 实例 | Free |
| 健康检查 | `/api/health` |
| 静态目录 | `/app/static` |
| 会话目录 | `/tmp/yanzheng-data`，临时存储 |
| 自动部署 | 关闭，更新时手动部署 |

## 账号中的操作

1. 登录自己的 Render 账号，打开上方部署入口；也可以在控制台选择 New → Blueprint 并指定该仓库。
2. 核对新建服务使用 **Free**，未增加付费服务、磁盘或数据库，再发起部署。如果页面要求付费套餐或账单验证，先停下核对，不切换为付费方案。
3. 等构建和健康检查通过，复制 Render 实际返回的 `onrender.com` 地址。不要根据服务名自行猜测地址。
4. 打开该地址，检查页面、`/api/health` 和“加载示例”流程，再把链接发给队友。

## 免费演示的边界

- Render 免费实例空闲后会休眠，下一次访问需要等待唤醒。
- 当前会话保存在容器临时文件中，休眠、重启或重新部署后可能丢失。演示前可重新加载内置示例。
- 这是共享演示环境：当前代码没有用户归属隔离，历史会话和材料接口可被其他访客访问。只使用示例或公开材料。
- 模型配置在此 Blueprint 中留空，避免默认产生模型 API 费用。规则提取、确认和审查可以运行；模型相关能力会显示降级结果或不可用状态。
- 如果要启用真实模型，在平台的服务端环境变量中配置 `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL` 并重新部署。模型服务是否收费及用量限制需要另行核对。
- `.env` 和本机会话数据由 `.dockerignore` 排除，不进入镜像，也不会随部署迁移。

免费资源政策以 [Render 官方说明](https://render.com/docs/free) 为准。长期保存学生材料需要另行设计持久化、账号权限和备份。

## 本地验证

```bash
# 仓库根目录;本机安装 Docker 后可执行
docker build -t yanzheng-demo .
docker run --rm -p 8080:8080 yanzheng-demo
```

访问 `http://localhost:8080`。当前提供的检查包括前端构建、后端测试及生产同源托管检查；本机没有 Docker 时，不能把这些检查表述为镜像构建已通过。
