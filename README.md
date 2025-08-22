# Piskel2Houdini - 地牢地图生成工具

## 一、项目概述

Piskel2Houdini 是一个基于 [Piskel](https://github.com/piskelapp/piskel) 开源画板工具和 Houdini 3D软件的地牢地图自动生成系统。该项目旨在通过"人工干预+自动化生成"的方式，创建高质量、可控的开放世界地牢地图。

## 二、项目背景

### 1.核心挑战

*   **纯自动化限制**：完全自动化的地图生成往往难以兼顾创造力、趣味性和设计意图
*   **质量控制**：需要确保生成的地图符合游戏设计要求和玩家体验标准
*   **迭代优化**：需要一个灵活的编辑和重新生成机制

### 2.解决方案

引入"中间环节人工干预"，通过前端交互工具作为人工编辑界面，与 Houdini（HDA）联动，形成"生成→编辑→再生成"的闭环工作流。

## 三、技术架构

### 1.系统组成

1.  **前端画板**：基于 Piskel 的浏览器端画板工具
2.  **本地后端**：基于插件化任务处理器的 Python 服务
3.  **Houdini 引擎**：HDA 文件和 hython 脚本
4.  **数据通信**：HTTP 接口和文件交换

### 2.核心流程

    用户编辑 → 数据导出 → 任务类型识别 → 对应处理器执行 → 结果返回 → 画板刷新

**详细流程**：
1. 前端发送请求：指定 `task_type`、`hip`、相关节点和参数
2. 调度服务根据 `task_type` 选择对应的任务处理器
3. 任务处理器执行自己的流程（如 hython + JSON转PNG、纹理导出、光照烘焙等）
4. 返回执行结果和状态信息

## 四、技术方案详解

### 1. 前端画板 (Piskel)

*   **功能**：提供直观的地牢图编辑界面
*   **数据格式**：支持二值图片（黑白像素）和二维数组（0/1矩阵）
*   **交互**：
    - 新增 Preferences → `PCG` 选项卡
    - 参数输入：`Area layout seed`（默认 9624，可清空再输入）
    - 按钮：`Step1_RoomGen`，点击后构造请求并发送到本地调度服务
*   **请求模板（前端内置）**：顶层包含 `task_type`、`uuid`，并在 `parms.room_file` 复用 `{uuid}.json`
*   **完整工作流**：一次请求完成 Houdini 生成 → JSON 导出 → PNG 图片转换
*   **技术栈**：JavaScript + HTML + CSS

### 2. 数据格式

*   **记录像素颜色的json**：
    *   黑色像素：非活动区
    *   红色像素：活动区域
    *   其他颜色：桥梁或者临时替代之用
*   **像素数据格式**：
    *   `pixels`：RGB 颜色数组，分量范围 [0,1] 浮点数
    *   `total_prims`：总像素数量（用于推断正方形画布尺寸）
    *   像素索引：从左下角开始，先 X 递增（左→右），再 Y 递增（下→上）

### 3. 通信机制

*   **导出方式**：画板将当前地牢图导出为图片或矩阵
*   **传输协议**：本地HTTP请求
*   **数据格式**：JSON + 二进制图片数据

#### 3.1 插件化任务处理器架构

- **核心思想**：调度服务通过 `task_type` 字段识别任务类型，调用对应的处理器执行具体流程。每种任务类型有自己的执行逻辑，便于扩展和维护。
- **优点**：
  - **可扩展性**：新增功能只需实现新的处理器类
  - **职责分离**：每种任务类型独立维护
  - **配置灵活**：不同任务类型可以有不同的必需字段和参数
  - **向后兼容**：现有功能包装为默认处理器

- **目前支持的任务类型**
    - **room_generation**（默认）：房间生成，执行 hython + JSON转PNG 流程

#### 3.2 流程
1. 前端/调用方向调度服务发送 `POST /cook`，指定 `task_type`
2. 调度服务根据 `task_type` 查找对应的任务处理器
3. 处理器验证必需字段，执行自己的流程
4. 返回执行结果

#### 3.3 接口
- **健康检查**：`GET /ping`
  - 返回：`{"status":"ok"}`
- **任务类型列表**：`GET /tasks`
  - 返回：`{"supported_tasks": [...], "default_task": "..."}`
- **执行任务**：`POST /cook`
  - 请求体（JSON）：
```json
{
  "task_type": "room_generation",                    # 可选，默认 "room_generation"
  "hip": "C:/path/to/file.hip",
  "cook_node": "/obj/geo1/OUT",                     # 根据任务类型可能需要不同字段
  "parm_node": "/obj/geo1/INPUT",                   # 可选
  "uuid": "0c8b1b54-2b3a-4a4e-8a6f-0c4d7b1a2f33",  # 必须
  "parms": { "area_layout_seed": 9624, "room_file": "0c8b1b54-2b3a-4a4e-8a6f-0c4d7b1a2f33.json" },
  "hython": "C:/Program Files/Side Effects Software/Houdini 19.5.716/bin/hython.exe",
  "hfs": "C:/Program Files/Side Effects Software/Houdini 19.5.716",
  "timeout_sec": 600,                                                               # 可选
  "post_timeout_sec": 10,                                                           # 可选，后置处理超时
  "post_wait_sec": 5                                                                # 可选，后置处理等待时间
}
```
  - 说明：
    - `task_type`：指定任务类型，决定使用哪个处理器
    - 优先使用 `hython` 字段；若未提供则尝试从 `hfs` 推断；都未提供则报错。
    - `parms` 为节点参数字典（标量或 tuple/数组）。不同任务类型的必需字段不同。
    - 服务端会将 `parms` 的键名统一规范化为小写，避免大小写不一致问题。
    - 前端需在请求顶层提供 `uuid`，并在需要时在 `parms` 中复用（如 `room_file` 使用 `{uuid}.json`）。
    - 新增可选参数：`post_timeout_sec`（默认 10s，json2jpg 超时）、`post_wait_sec`（默认 min(5, post_timeout_sec)，等待文件出现时间）
  - 成功响应（示例）：
```json
{
  "ok": true,
  "cook_node": "/obj/geo1/OUT",
  "parm_node": "/obj/geo1/INPUT",
  "elapsed_ms": 245,
  "node_errors": [],
  "missing_parms": [],
  "parms": {"area_layout_seed": 9624, "room_file": "0c8b1b54-2b3a-4a4e-8a6f-0c4d7b1a2f33.json"},
  "elapsed_ms_dispatch": 312,
  "post": {
    "ok": true,
    "returncode": 0,
    "stdout": "",
    "stderr": "",
    "json": {
      "ok": true,
      "uuid": "0c8b1b54-2b3a-4a4e-8a6f-0c4d7b1a2f33",
      "path_json": "I:/Ugit_Proj/moco_pcg/export/serve/0c8b1b54-2b3a-4a4e-8a6f-0c4d7b1a2f33.json",
      "path_png": "I:/Ugit_Proj/moco_pcg/export/serve/0c8b1b54-2b3a-4a4e-8a6f-0c4d7b1a2f33.png",
      "exists": true,
      "width": 64,
      "height": 64,
      "pixels_written": 4096
    },
    "elapsed_ms_post": 120
  }
}
```
  - 失败响应（示例）：
```json
{
  "ok": false,
  "error": "错误信息",
  "traceback": "堆栈",
  "returncode": 1,
  "stdout": "...",
  "stderr": "..."
}
```

#### 3.4 统一日志系统与跨域（CORS）
- **统一日志系统**：采用OOP设计，支持两类日志
  - **详细日志**：`<hip所在目录>/export/serve/log/detail/{uuid}.json`
    - 内容：`uuid`、`ok`、`elapsed_ms_dispatch`、`returncode`、`stdout`、`stderr`、`worker_json`、`post`（含 json2jpg 结果）、`request`（含小写化后的 `parms`）
  - **用户宏观日志**：`<hip所在目录>/export/serve/log/users/{user_id}.json`
    - 结构：`stack`（当前操作栈）+ `history`（被覆盖的历史操作）
    - 支持：相同 `process_name` 的覆写逻辑，被截断的后续操作自动移入 `history`
    - 命名：`{users}_{YYYYMMDDHHmm}.json`（如：`dallas_202508221713.json`）
- **日志记录时机**：仅在任务成功（`ok == true`）时写入用户栈日志，失败不写入
- **跨域**：调度服务已开启基础 CORS 支持，允许从 `http://localhost:9901` 等本地页面访问

#### 3.5 约定
- **hython 解析**：
  - 有 `hython` → 直接使用
  - 无 `hython` 且有 `hfs`/环境变量 `HFS` → 组合 `${HFS}/bin/hython.exe`
- **参数设置**：
  - 工作脚本会依次尝试 `parm.set(value)` 与 `parmTuple.set([...])`
  - 找不到的参数返回在 `missing_parms`
- **超时**：默认 600s，可在请求体 `timeout_sec` 指定
- **用户标识**：
  - 前端每次启动生成新的 `user_time`（`YYYYMMDDHHmm`格式）
  - 请求体需包含：`user_id`（`{users}_{user_time}`）、`request_time`（ISO8601格式）

### 4. 本地Python脚本

*   **功能**：接收前端请求、解析数据、调用Houdini
*   **核心组件**：
    *   HTTP 调度服务（Dispatcher）：基于插件化架构的 Flask 服务，根据 `task_type` 路由到对应处理器
    *   任务处理器基类（BaseTaskProcessor）：定义处理器接口，支持必需字段验证
    *   图像处理模块（基于 Pillow 库）
    *   执行Houdini任务模块
    *   结果返回处理

### 5. Houdini处理

*   **输入**：解析后的地牢json文件
*   **处理**：基于HDA文件进行地图生成和优化
*   **输出**：新的地牢数据（JSON 格式 + PNG 图片）

### 6. 结果返回

*   **数据流**：Python脚本将Houdini生成的结果 + PNG图片转换结果返回给前端
*   **画板更新**：自动刷新显示新生成的地牢图
*   **迭代支持**：用户可继续编辑或触发下一轮生成

## 五、安装和使用

### 1.环境要求

*   Node.js 和 npm
*   Python 3.7+
*   Pillow 图像处理库：`pip install pillow`
*   Houdini 软件（支持 hython）
*   现代浏览器（Chrome、Firefox、Edge）

### 2.测试步骤

#### 2.1 安装并配置piskel

*   install node and grunt-cli npm install grunt-cli -g.
*   clone the repository <https://github.com/juliandescottes/piskel.git>
*   run npm install
*   install CasperJS (needed for integration tests)

#### 2.2 测试piske本地运行
*   `grunt`：grunt会将piskel构建到仓库根目录下的/dest文件夹中。
*   `grunt serve`：
    *   build the application构建应用程序
    *   start a server on port 9001 (serving dest folder). 在端口9001上启动服务器（服务dest文件夹）
    *   open a browser on http://localhost:9001
    *   watch for changes, and rebuild the application if needed. 观察更改，并在需要时重新构建应用程序
*   `grunt play`：
    *   start a server on port 9901 (serving /src folder). 在端口9901上启动服务器（服务/src文件夹）
    *   open a browser on http://localhost:9901/?debug. 打开浏览器http://localhost:9901/?debug
*   `grunt test`：
    *   leading indent validation 前导缩进验证
    *   perform jshint validation 执行jshint验证
    *   execute unit tests 执行单元测试
    *   execute integration tests 执行集成测试

#### 2.3 Houdini服务端本地测试
*   启动监听服务：`python houdini\dispatcher_server.py --host 0.0.0.0 --port 5050 `
*   powershell进行ping通测试：`curl http://127.0.0.1:5050/ping `
*   查看支持的任务类型：`curl http://127.0.0.1:5050/tasks `
*   powershell发送伪请求，测试Houdini执行结果，例如：
```powershell
$body = @{
    task_type = "room_generation"
    hip = "I:\Ugit_Proj\moco_pcg\dev_oa_ui.hip"
    cook_node = "/obj/UI_part_01/cook_001"
    parm_node = "/obj/UI_part_01/SETTING"
    parms = @{
        area_layout_seed = 9624
    }
    hython = "C:\Program Files\Side Effects Software\Houdini 20.5.487\bin\hython.exe"
    timeout_sec = 300
} | ConvertTo-Json -Depth 5

Invoke-RestMethod -Uri "http://127.0.0.1:5050/cook" `
    -Method POST `
    -Body $body `
    -ContentType "application/json"
```

#### 2.4 Piskel通信测试
*   打开 `grunt play` 页面：`http://localhost:9901/?debug`
*   在 Preferences → `PCG` 中设置 `Area layout seed`，点击 `Step1_RoomGen`
*   请求示例（由前端自动生成并发送）：
```json
{
  "task_type": "room_generation",
  "hip": "I:/Ugit_Proj/moco_pcg/dev_oa_ui.hip",
  "cook_node": "/obj/UI_part_01/cook_001",
  "parm_node": "/obj/UI_part_01/SETTING",
  "uuid": "<前端生成的uuid>",
  "parms": { "area_layout_seed": 9624, "room_file": "<前端生成的uuid>.json" },
  "hython": "C:/Program Files/Side Effects Software/Houdini 20.5.487/bin/hython.exe",
  "timeout_sec": 300
}
```
*   观察调度服务控制台与日志文件 `<hip>/export/serve/log/{uuid}.json`
*   检查生成的文件：
      - `<hip>/export/serve/{uuid}.json`：Houdini 导出的像素数据
      - `<hip>/export/serve/{uuid}.png`：转换后的 PNG 图片


### 3.使用方法

#### 3.1 服务部署
*   在`PcgPreferencesController.js`中修改监听服务的url

#### 3.2 新增其他前端任务
*   设定HDA的基本功能，确认需要发送的参数等
*   设定前端，按照模板发送请求，含有相关任务信息和参数信息
*   实现新的处理器类的基本功能，在 TASK_PROCESSORS 中注册，确认HDA和HIP的调用

## 开发计划

### 第一阶段-数值通信(已完成)

*   [x] 前端基础画板功能
*   [x] 前端请求发送功能：测试发送参数功能-（PCG/Step1_RoomGen，顶层 uuid + parms）
*   [x] 后端服务部分：请求监听dispatcher服务与执行调度cook_worker服务
*   [x] 后端逻辑部分：适用于交互流程的拆解的布局生成的PCG逻辑工程
*   [x] 数据传递格式标准统一 
*   [x] 后端数据处理：实现json与png的自动转换
*   [x] 插件化任务处理器架构重构
*   [x] 前端接受数据自动加载

### 第二阶段-前端界面功能

  *   [x] 统一日志系统（OOP设计）
  *   [x] 详细日志：`export/serve/log/detail/{uuid}.json`
  *   [x] 用户宏观日志：`export/serve/log/users/{user_id}.json`
  *   [x] 支持操作栈覆写与历史迁移
  *   [x] 完成step2/step3-发送房间信息给Hython服务，生成链接通路
  *   [x] 前端用户管理
  *   [x] Users输入框（支持随机生成）
  *   [x] 每次启动生成新的user_time
  *   [x] 请求自动附加user_id与request_time

### 第三阶段-多人协作工具

*   [x] 地牢布局生成算法
*   [ ] 任务池功能

### 新增功能说明

#### 统一日志系统架构
- **设计理念**：采用OOP设计，统一管理两类日志的写入
- **核心组件**：
  - `LogSystem`：统一日志系统类，提供detail与users日志写入接口
  - **详细日志**：按任务uuid记录完整执行信息
  - **用户宏观日志**：按用户会话记录操作栈与历史
- **特性**：
  - 原子写入：使用临时文件+重命名确保数据完整性
  - 自动目录创建：按需创建日志目录结构
  - 栈式管理：支持相同process_name的覆写逻辑
  - 历史迁移：被覆盖的操作自动移入history

#### 插件化任务处理器架构
- **设计理念**：每种任务类型对应一个处理器类，处理器负责自己的执行流程
- **核心组件**：
  - `BaseTaskProcessor`：抽象基类，定义处理器接口
  - `RoomGenerationProcessor`：房间生成处理器（hython + JSON转PNG）
  - `RoomRegenProcessor`：房间信息更新处理器（PNG→JSON + hython pressButton）
  - `TextureExportProcessor`：纹理导出处理器（待实现）
  - `LightingBakeProcessor`：光照烘焙处理器（待实现）
- **优势**：
  - 可扩展性：新增功能只需实现新的处理器类
  - 职责分离：每种任务类型独立维护
  - 配置灵活：不同任务类型可以有不同的必需字段和参数
  - 向后兼容：现有功能包装为默认处理器

#### JSON → PNG 转换
- **脚本**：`houdini/json2jpg.py`（名称保留，实际输出 PNG）
- **功能**：读取生成的 `<hip_dir>/export/serve/{uuid}.json`，转换为 `<hip_dir>/export/serve/{uuid}.png`
- **像素处理**：
  - 支持 `pixels` 为列表或映射对象格式
  - RGB 分量范围 [0,1] → [0,255]
  - 像素索引：左下角原点，先 X 后 Y 递增
  - 画布尺寸：根据 `total_prims` 推断正方形（要求完全平方数）
- **输出格式**：PNG（无损，像素完美保真）
- **集成方式**：由 `RoomGenerationProcessor` 在 hython 成功后同步执行

#### 响应结构更新
- 新增 `post` 字段，包含 json2jpg 执行结果
- `post.json` 包含：`path_json`、`path_png`、`width`、`height`、`pixels_written` 等
- 支持 `post_timeout_sec` 和 `post_wait_sec` 参数控制后置处理超时和等待时间

#### 文件输出
- **JSON 数据**：`<hip>/export/serve/{uuid}.json`
- **PNG 图片**：`<hip>/export/serve/{uuid}.png`
- **日志记录**：
  - 详细日志：`<hip>/export/serve/log/detail/{uuid}.json`
  - 用户宏观日志：`<hip>/export/serve/log/users/{users}_{YYYYMMDDHHmm}.json`

#### 新增API接口
- **`GET /tasks`**：列出支持的任务类型和默认任务类型
- **向后兼容**：不指定 `task_type` 时默认使用 `room_generation`

## 贡献指南

欢迎贡献代码、报告问题或提出建议！

### 贡献方式

*   提交 Issue 报告问题
*   提交 Pull Request 贡献代码
*   参与项目讨论和设计

### 开发环境设置

请参考 [Piskel 开发文档](https://github.com/piskelapp/piskel/wiki) 了解前端开发环境设置。

## 许可证

本项目基于 Apache License 2.0 开源协议，详见 [LICENSE](LICENSE) 文件。

## 致谢

*   [Piskel](https://github.com/piskelapp/piskel) - 优秀的开源画板工具
*   [Houdini](https://www.sidefx.com/) - 强大的3D软件平台
*   所有为开源社区做出贡献的开发者

***

**注意**：本项目仍在开发中，功能可能不完整。如有问题或建议，请通过 Issue 与我们联系。