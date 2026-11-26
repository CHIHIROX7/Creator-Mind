# 用户与认证模块调研报告

调研日期：2026-11-22

调研对象：当前 `Creator-Mind` 仓库。

调研阶段：需求范围、系统边界、影响评估与选型决策；不包含实施方案。

## 一、结论摘要

**这不是在已有用户体系上补一个登录入口，而是让当前单工作区 MVP 建立可信身份和用户数据边界。**

目前最直接受影响的业务是已经接通的会话与消息。前后端都没有认证生命周期，数据库也没有用户或会话所有者。登录成功本身不能解决跨用户读写问题。

建议围绕五个问题理解任务：

1. **身份：**账号从哪里来，谁能注册、登录及使用系统？
2. **认证状态：**身份如何持续有效，退出、过期和禁用意味着什么？
3. **授权：**用户能操作哪些会话、消息，以及未来的素材、记忆和任务？
4. **数据归属：**新增数据属于谁，现有无主数据如何处置？
5. **运行边界：**系统用于本机、私有多人实例还是公网服务，谁承担认证运维？

**主要风险排序：存量数据归属与对象级授权 > 登录状态及前端数据残留 > 公网部署边界 > 未来 Agent/任务的身份传递。**

本报告中的建议均为条件性判断，没有替你决定身份提供方、会话技术、注册方式或权限模型。

## 二、调研依据与限制

本次只读分析了：

- `backend/app`：应用入口、路由、配置、ORM、Schema、Agent 工作流与 Worker。
- `backend/alembic`、后端依赖清单及现有测试。
- `frontend/src`：路由、布局、页面、状态管理、全部现有 API 封装及测试。
- 前端依赖、开发代理、Dockerfile。
- `README.md`、`docs/architecture.md`、`compose.yaml` 与开发脚本。

未读取 `.env` 中的秘密，未访问运行中的数据库，未执行测试、迁移、模型调用或安装依赖；未解析项目简介 PDF。未修改业务代码。

因此：

- “已实现”指仓库中存在实现及调用关系，不代表运行环境已验证可用。
- “未发现”仅限本次仓库范围，不代表外部身份服务或部署平台没有相关能力。
- 数据库是否已有业务数据、实际部署是否覆盖开发默认值、迁移是否已执行，仍需核实。
- `README.md` 部分能力说明落后于代码：它仍称未实现内容持久化和真实模型调用，但代码已有会话/消息持久化及独立意图分类模型调用。后者尚未接入聊天发送链路。**范围评估以实际代码为准，不将规划视为现有能力。**

## 三、现有结构与能力盘点

### 3.1 架构概况

| 层次 | 当前情况 | 对任务的意义 |
|---|---|---|
| 前端 | Vue 3、TypeScript、Vue Router、Pinia、Vite、Tiptap | 已有应用外壳，没有身份状态或认证交互 |
| 后端 | FastAPI、Pydantic 2、SQLAlchemy 2 异步会话 | 有 API 和数据访问基础，没有认证或对象授权 |
| 数据库 | PostgreSQL 16、Alembic，已启用 pgvector 扩展 | 可承载账号及归属数据；不需要因认证默认更换数据库 |
| Redis / Worker | Redis 连接与 Celery 配置存在，Worker 仅有 ping 任务 | 不是现成的认证会话、撤销、限流或生成任务体系 |
| Agent | 意图分类、工具契约和同步工作流；上下文可传 `user_id` | 有身份传递接口线索，没有身份验证或资源授权保证 |
| 对象存储 | MinIO/S3 配置存在 | 没有发现已接通的上传、签名访问或用户文件隔离 |
| 运行环境 | 本地基础设施与可选完整容器开发环境 | 不是已完成安全加固的生产部署模板 |

后端与前端依赖清单未显式声明现成的认证 SDK；配置中的 `secret_key` 只是占位字段，不能视为已有签名或令牌验证能力。

### 3.2 页面与业务成熟度

前端有六个业务页面：工作台、作品与素材库、多 Agent 创作、对话、个性化记忆、系统设置，全部位于同一业务布局下。

| 能力 | 当前成熟度 | 本次边界 |
|---|---|---|
| 会话与消息 | 已接通列表、新建、改名、删除、消息读取与保存 | **必须评估真实的跨用户隔离** |
| 富文本创作 | 编辑、撤销、重做可用；保存版本未接通 | 登录跳转或退出会影响未保存内容的去留 |
| 素材、记忆、工作台统计 | 主要为静态示例或占位展示 | 不应把完整业务模块计入认证任务 |
| 用户与认证 | 无用户模型、登录退出、身份恢复、路由访问限制 | 新增能力，不能直接复用现有认证模块 |
| 团队/项目/组织 | 没有实际模型或业务路由 | “工作空间”文案不等于已有多租户模型 |
| 流式聊天与后台生成 | 未发现 SSE、WebSocket 或生成任务 API | 是未来扩展边界，不是现有流式链路适配 |

顶部的“创作者”只是静态文字。聊天里的“会话”是业务会话，不是登录 Session；消息的 `role='user'` 也不是账号身份。

### 3.3 当前 API 与授权缺口

默认业务前缀为 `/api/v1`。现有后端业务 API：

| 方法与路径 | 当前行为 | 需要界定的授权边界 |
|---|---|---|
| `GET /api/v1/conversations` | 返回全局最近 200 个会话 | 用户只能发现允许访问的资源 |
| `POST /api/v1/conversations` | 创建无所有者的会话 | 创建后资源必须有明确归属 |
| `GET /api/v1/conversations/{id}` | 按 UUID 检查存在并读取 | 知道 UUID 不等于有权访问 |
| `PATCH /api/v1/conversations/{id}` | 修改标题 | 写入权限不能仅依赖存在检查 |
| `DELETE /api/v1/conversations/{id}` | 删除会话并级联删除消息 | 删除权限与数据保留政策 |
| `GET /api/v1/conversations/{id}/messages` | 读取该会话消息 | 子资源必须服从父会话访问边界 |
| `POST /api/v1/conversations/{id}/messages` | 保存客户端提交的消息 | 会话权限、消息作者及来源可信度 |

另有根入口、健康检查、就绪检查及 FastAPI 默认文档入口。**这些入口是否公开，应单独划定；不能把“所有业务资源需认证”误解为所有探针都必须登录。**

当前代码没有可信用户依赖，也没有列表归属过滤或对象级授权。按仓库中的默认实现，能访问接口的调用方可以列出会话并读写对应资源，不能直接按多人服务公开使用。关键证据见附录 E1、E2。

## 四、任务范围与边界

### 4.1 建议作为首期必要范围讨论

以下是功能责任，不是接口、表结构或施工步骤：

| 责任域 | 必须回答的问题 |
|---|---|
| 用户身份 | 系统用户如何识别？账号由谁创建？哪些资料属于本地用户信息，哪些由外部身份方管理？ |
| 认证生命周期 | 登录、退出、刷新页面后的身份恢复、过期、被禁用时分别呈现什么行为？ |
| 资源授权 | 用户能列出、读取、修改、删除哪些会话及消息？后台直接访问是否同样受约束？ |
| 数据归属 | 新会话的所有者是谁？消息继承谁的访问权限？是否另需记录消息作者？ |
| 前端身份边界 | 业务页面、当前用户展示、失效提示、重新登录和退出后的数据清理是什么语义？ |
| 遗留数据 | 当前无主会话和消息是否存在？如何确认归属？无法确认的记录怎样处理？ |
| 基础安全责任 | 凭证保护、失败尝试限制、会话失效、敏感日志及部署安全由谁承担？ |
| 验收边界 | 如何证明用户 A 不能访问或影响用户 B，而不只是证明登录按钮可用？ |

即使只做最小版本，**对象授权、可靠退出、密码/令牌保护不能作为“以后再补”的非必要项**。具体安全等级则取决于是否公网开放。

### 4.2 必须明确决策，但不应自动纳入首期

- 开放注册、邀请、管理员开户，以及初始管理主体的来源。
- 登录标识采用邮箱、用户名、手机号或外部账号；是否需要验证和恢复通道。
- 账号资料编辑、修改密码、密码重置、账号禁用和删除。
- 是否有管理员；管理员能管理账号还是也能读取私有创作内容。
- 多设备登录、全部设备退出、强制撤销与跨标签页状态一致性。
- 重新登录后是否恢复未提交草稿和原访问页面。
- 账号删除后的业务内容、未来素材、向量、记忆及衍生数据保留政策。

不能默认“管理员”天然拥有全部私有内容访问权，也不能默认“删除账号”等于物理级联删除全部业务数据。

### 4.3 建议明确排除或作为后续独立模块

- 团队、组织、项目、成员邀请、复杂 RBAC/ABAC、共享和协作。
- 同时实现多个第三方登录渠道、企业 SSO、MFA、设备风险识别。
- 完整素材上传、RAG、记忆、草稿版本、生成任务与流式聊天。
- 用量计费、订阅、付款、用户自带模型密钥管理。
- 因认证进行全面前后端重构，或提前搭建通用权限平台。

这些能力可能需要引用用户身份，但**依赖身份不等于必须与本次一起完成**。如果你的目标是企业 SSO 或团队协作，上述边界需要相应重划。

### 4.4 与 Agent 和未来后台任务的责任分界

现有 `WorkflowContext` 允许调用方传入 `user_id`，但它是可选字段，执行过程只传递上下文，不验证用户或资源权限。工具契约也不等于素材与草稿访问控制。

应在范围上明确：

- 认证模块负责建立可信调用主体及其状态。
- 各业务模块负责判定该主体是否能使用具体素材、会话、草稿和任务。
- Agent 或模型抽取的资源 ID 不能提供权限，模型不能决定“当前用户是谁”。
- 未来任务结果、检索范围、对象存储访问需要延续同一归属边界。

目前没有已接通的后台生成与流式持久化，不应将其完整实现算进这次工作；但未来“退出或停用后任务能否继续、结果谁能读取”的规则需要提前留下边界。

## 五、影响面评估

“高/中/条件性”表示改动关联与风险，不是工期估计。

| 位置 | 影响 | 等级与原因 |
|---|---|---|
| `backend/app/api/routes/conversations.py` | 全部会话与消息 API 的访问语义 | **高**：已实现业务，当前只有存在检查和全局列表 |
| `backend/app/models/conversation.py`、`backend/alembic` | 数据归属、约束、存量记录与删除关系 | **高**：缺少身份字段，旧数据无法自行推断所有者 |
| `backend/app/schemas/conversation.py` | 客户端可提交什么，哪些字段可信 | **中至高**：消息角色可由客户端指定；角色不等于作者或账号权限 |
| `backend/app/main.py`、`backend/app/api/router.py`、`backend/app/core/config.py` | 公共/私有 API 边界、认证配置、跨域与秘密管理 | **高**：没有现成身份验证基础，部署形态影响契约 |
| `frontend/src/router/index.ts`、`frontend/src/App.vue` | 启动身份确认、业务访问、登录后返回 | **高**：当前没有认证状态或受限页面概念 |
| `frontend/src/api/client.ts`、`frontend/src/api/conversations.ts` | 凭证与认证失败的请求行为 | **高**：两套独立封装，聊天不经过健康检查客户端 |
| `frontend/src/views/ConversationsView.vue` | 当前会话、消息、弹窗目标、发送中状态 | **高**：数据和未完成请求没有账号切换边界 |
| `frontend/src/views/CreationView.vue` | 未保存标题、正文及编辑历史 | **中**：临时编辑可用，但没有持久化恢复 |
| `frontend/src/components/AppHeader.vue`、`frontend/src/layouts/AppLayout.vue`、`frontend/src/stores` | 身份呈现、退出入口、全局身份状态 | **中**：已有布局可承载交互，没有用户状态可复用 |
| `frontend/src/views/SettingsView.vue` | 个人设置与系统运行设置的区分 | **条件性**：当前页面主要展示服务状态，不能默认升级为账号管理 |
| `backend/app/agents/workflow.py`、`backend/app/agents/tools.py` | 可信身份上下文与未来工具权限责任 | **条件性**：已有传递接口，但真实业务执行器尚未接通 |
| `backend/app/workers`、未来检索和对象存储 | 后台执行、结果归属、文件访问 | **后续关联**：避免绕过身份，不默认新增完整业务链路 |
| `compose.yaml`、Dockerfile、开发代理与运行配置 | HTTP/HTTPS、同源/跨域、密钥、发布迁移 | **公网时高**：现有配置是开发环境 |
| 后前端测试及项目文档 | 认证与越权验收、实际能力说明 | **高**：现有测试不能证明跨用户隔离 |

### 5.1 前端容易漏估的影响

1. **两套网络入口。**健康检查客户端保留结构化 HTTP 状态，聊天客户端抛普通 `Error`；两处都没有登录失效专项处理。不能只评估一个公共客户端。
2. **健康状态不是身份状态。**后端在线，不代表当前用户已登录；未授权也不等于后端不可达。
3. **账号切换的数据残留。**对话列表、消息、活动 ID 和删除目标都在页面局部状态中，没有与账号绑定。
4. **未完成请求。**当前只处理切换对话时消息读取的先后顺序，没有覆盖账号变化。旧请求的返回不能落到新账号视图。
5. **临时内容丢失。**未发现 `localStorage`、`sessionStorage`、IndexedDB 或草稿持久化；登录跳转导致页面卸载可能丢失聊天输入和编辑内容。
6. **不能默认重放操作。**消息保存或删除可能已提交，只是响应未到达；重新登录后自动重试不能作为当然行为。

两套 `fetch` 没有显式认证头或 `credentials` 配置，但这**不意味着不会携带同源 Cookie**；浏览器默认行为与跨域配置必须分开看。

### 5.2 存量数据是独立风险，不是迁移小细节

现有 `Conversation` 没有所有者，`Message` 只有会话外键和内容角色。没有已记录的创建者身份，无法仅凭这些字段可靠恢复归属。

因此不能默认为：

- 历史数据属于首个注册者或最近登录者。
- 全部新账号都可看到历史记录。
- 留空所有者可以长期作为访问控制例外。
- 消息中的 `role='user'` 能用来认领数据。

若数据库为空，迁移与政策负担相对小；若已积累真实内容，归属确认、备份、回退和不可错误公开的要求会明显扩大范围。

### 5.3 运行和验证约束

- 当前 Compose 后端开启 `development`、`debug` 和 `--reload`，前端启动 Vite 开发服务器；未发现生产 TLS 终止或反代配置。
- CORS 允许 credentials 不是认证机制，也不能限制非浏览器调用方。
- 数据库、Redis、MinIO 有宿主机端口映射，不能把 `localhost` 访问说明当成仅本机可访问的安全保证。
- `secret_key` 有开发占位值；这既不证明已经用于认证，也不证明部署时已覆盖。
- Compose 中 API 启动前执行迁移；其他启动路径不同。增加账号及归属数据后，发布、备份、迁移执行主体和回退都需纳入运行边界。
- 现有测试主要覆盖健康检查和 Agent 逻辑。`user_id` 传递测试只是传递验证，不是拒绝越权验证；未发现认证和会话隔离集成测试。

这些是与认证直接相关的约束，不是建议本次顺带全面改造运维。

## 六、技术与产品决策选项

### 6.1 决策总表

| 决策 | 选项 | 我的看法 |
|---|---|---|
| 部署目标 | 本机单人；私有多人；公网服务 | **第一优先级。**公网开放会提升恢复通道、抗滥用、HTTPS、秘密和撤销的要求。现有运行配置不能直接当公网方案 |
| 隔离主体 | 个人用户；团队/组织工作区 | 文档规划的是用户级隔离，没有团队实体。若无明确协作需求，个人私有空间范围更清楚；团队模式应显式扩大任务 |
| 身份来源 | 本地账号；外部 OIDC 身份服务；已有企业 SSO | 本地账号自主、适合独立部署，但需承担密码、恢复、禁用与攻击防护；已有身份平台时不宜重复造账户体系 |
| 外部身份服务运维 | 托管服务；自托管身份服务 | 托管降低认证运维负担，增加费用、外部依赖与数据边界；自托管更可控，但本项目需承担额外服务运行。均不能代替业务资源授权 |
| 开户方式 | 开放注册；邀请；管理侧预建；仅外部授权用户 | 私有多人实例可优先考虑受控开户；公网开放注册会带来验证、自动化滥用与模型成本风险。不自动引入邮件/短信服务 |
| 登录标识与恢复 | 用户名；邮箱；手机号；外部身份标识 | 如果邮箱验证和密码恢复是明确需求，邮箱有价值；手机号引入短信成本及额外个人信息，不宜无理由加入 |
| 登录状态 | 服务端不透明 Session；Access/Refresh Token 体系 | 当前主要是浏览器应用，服务端 Session 值得优先比较，退出与撤销语义直观；若有移动端、开放 API 或跨服务需求，令牌体系更有理由，但续期和撤销并不会自动简化 |
| 数据隔离防线 | 应用层对象授权；应用授权叠加 PostgreSQL RLS | 当前核心是形成一致业务授权。RLS 可增加纵深防线，但会扩大数据库连接上下文、Worker 和迁移约束；不建议未经决策默认纳入 |
| 存量数据政策 | 经确认归属指定主体；隔离待认领/归档；明确授权的共享遗留空间 | 优先“不错误公开”。若无法证明归属，隔离比自动分配安全；共享仅在明确产品规则和授权下成立 |
| 账户生命周期 | 禁用；用户自行注销；管理侧删除；保留/匿名化策略 | 禁用、登录失效和数据删除是三个不同问题。永久删除规则应先界定，不能随用户表级联逻辑自动决定 |
| 权限复杂度 | 所有者权限；有限管理能力；完整 RBAC/ABAC | 首期可围绕所有者边界讨论；账号管理并不必然需要通用 RBAC，更不必然赋予管理者内容读取权 |
| 模型费用与凭证 | 平台统一密钥；用户自带密钥；用户额度 | 当前只有服务级模型配置，且未接通聊天生成。不默认做账单系统；公网注册和未来生成至少需要明确滥用与费用责任 |

### 6.2 两个容易混淆的技术问题

**身份来源与登录状态是不同决策。**选择 OIDC 并不意味着前端一定要长期持有 JWT；本地账号也不意味着一定要使用服务端 Session。

**Cookie 是凭证传输/存储机制，JWT 是令牌格式。**令牌也可以通过 Cookie 传输。应先看浏览器/多客户端目标、立即退出需求、同源/跨域部署及运维责任，而不是先比较“Cookie 和 JWT 谁更先进”。

如果使用自动随请求发送的 Cookie，就必须界定 CSRF 防护；如果由浏览器持有 Bearer Token，也要界定 XSS 暴露面、存储、续期及撤销责任。这些安全责任不能因选了某个名词而消失。

### 6.3 当前可以保留、不急于细选的部分

- Vue、FastAPI、PostgreSQL 等现有技术栈没有显示出必须因认证更换的原因。
- 已有 Redis 可作为某些会话或限流选择的基础，但“已经配置 Redis”不能替代对可用性和会话存储责任的决策。
- 具体密码哈希库、JWT/OIDC 客户端库及供应商 SDK，应在身份来源确定后做兼容性与维护评估。若选择本地密码，需要明确现代密码哈希和安全恢复的责任，不应设计自定义密码加密。
- 此阶段不决定接口命名、数据库字段、令牌有效期、密码规则、迁移脚本、路由守卫或中间件写法。

## 七、范围验收的思路

这里定义用户可感知的正确结果，不给具体测试或实现方案：

1. 已登录用户只能发现和操作自己的会话与消息；替换资源 ID 或直接调用 API 不能绕过授权。
2. 未登录、认证过期、主动退出、账号禁用的行为可区分；退出效果符合承诺的设备和撤销范围。
3. 刷新页面、直接访问业务 URL、重新登录后返回的体验有明确约定，不把私有内容闪现给未确认身份的用户。
4. 切换账号后，旧消息、弹窗目标、临时内容和旧请求返回不会混入新账号。
5. 旧数据按选定政策可访问或被隔离，不会因没有所有者被默认公开。
6. 对会话的授权同时覆盖消息；内容角色不能冒充账号权限或可信系统来源。
7. 私有内容、密码和令牌不泄漏到前端构建配置或日志；公网部署满足约定的传输与基础设施边界。
8. Agent 上下文携带身份不被当成已经授权；未来业务模块不能绕过用户资源边界。

## 八、需要你优先拍板的事项

按依赖顺序，建议先回答以下六组问题，之后再确定首期范围和工作量：

1. **使用场景：**本机工具、私有多人实例还是公网服务？首期是否只支持浏览器？
2. **数据主体：**个人私有空间还是团队/组织空间？是否有共享需求？
3. **账号来源与开户：**本地账号还是外部 OIDC/SSO？开放注册、受邀还是预建？
4. **生命周期：**首期要不要邮箱验证、恢复密码、禁用、注销和多设备退出？未保存草稿遇到失效时是否必须保留？
5. **历史数据：**当前数据库是否已有需保留的真实会话？谁有权确认归属？不能确认的内容是否允许隔离？
6. **管理与运行责任：**是否需要管理员，管理权限止于账号还是包含私有内容？谁管理 HTTPS、认证秘密、备份和发布迁移？

**建议的思考顺序：先定义信任与数据边界，再确认必要用户体验，最后选择身份与会话技术。**如果目标只是“浏览器上的私有多人个人创作空间”，范围可以保持聚焦；如果同时要求公网自助注册、团队协作、SSO、MFA、计费或完整生成链路，就应拆成独立需求，而不是统称“加一个用户模块”。

## 附录：关键代码证据

以下为本次读取时的仓库片段，行号可能随后续编辑变化。

### E1：后端明确没有认证与隔离

```1:5:backend/app/api/routes/conversations.py
"""CRUD endpoints for the MVP's local single-workspace conversations.

Authentication/tenant isolation is not implemented in the starter project;
add authorization before exposing these endpoints publicly.
"""
```

```29:33:backend/app/api/routes/conversations.py
async def require_conversation(db: AsyncSession, conversation_id: UUID) -> Conversation:
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="对话不存在")
    return conversation
```

### E2：当前会话没有归属，消息归属会话

```13:17:backend/app/models/conversation.py
class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="新对话")
```

```29:37:backend/app/models/conversation.py
class Message(Base):
    __tablename__ = "messages"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
```

### E3：聊天独立封装请求，并抛普通错误

```23:29:frontend/src/api/conversations.ts
  if (!response.ok) {
    let detail = `请求失败（HTTP ${response.status}）`
    try {
      const body = await response.json() as { detail?: string }
      if (typeof body.detail === 'string') detail = body.detail
    } catch { /* non-JSON error */ }
    throw new Error(detail)
```

健康检查使用另一套客户端，并保留状态：

```30:32:frontend/src/api/client.ts
  if (!response.ok) {
    throw new ApiError(`请求失败（HTTP ${response.status}）`, response.status)
  }
```

### E4：聊天数据与草稿目前是页面局部状态

```6:12:frontend/src/views/ConversationsView.vue
const conversations = ref<Conversation[]>([])
const activeId = ref<string | null>(null)
const messages = ref<Message[]>([])
const draft = ref('')
const busy = ref(false)
const loading = ref(true)
const error = ref('')
```

### E5：工作流有身份传递契约，但字段可选

```17:22:backend/app/agents/workflow.py
class WorkflowContext(TypedDict, total=False):
    """Trusted execution metadata supplied by the API/task caller, never by the LLM."""

    user_id: str
    conversation_id: str
    task_id: str
```

### E6：消息角色由客户端提交，不是认证角色

```26:28:backend/app/schemas/conversation.py
class MessageCreate(BaseModel):
    role: Literal['user', 'assistant', 'system'] = 'user'
    content: str = Field(min_length=1, max_length=20000)
```

### E7：当前容器运行模式明确是开发环境

```52:57:compose.yaml
    command: >
      /bin/sh -c "alembic upgrade head &&
      uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"
    environment:
      CREATORMIND_ENVIRONMENT: development
      CREATORMIND_DEBUG: "true"
```

### E8：前端现有路由回调只修改标题，身份展示是静态文字

```57:60:frontend/src/router/index.ts
router.afterEach((to) => {
  const title = typeof to.meta.title === 'string' ? to.meta.title : 'CreatorMind'
  document.title = `${title} · CreatorMind`
})
```

```59:61:frontend/src/components/AppHeader.vue
      <div class="grid h-10 w-10 place-items-center rounded-full bg-ink-950 text-xs font-semibold text-white">
        创作者
      </div>
```
