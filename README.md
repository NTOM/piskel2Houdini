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
2.  **本地后端**：Python 服务脚本
3.  **Houdini 引擎**：HDA 文件和 hython 脚本
4.  **数据通信**：HTTP 接口和文件交换

### 2.核心流程

    用户编辑 → 数据导出 → Python处理 → Houdini生成 → 结果返回 → 画板刷新

**详细流程**：
1. 前端发送请求：指定 `hip`、`cook_node`（执行节点）、`parm_node`（参数节点，可选）
2. 调度服务启动 hython 子进程
3. 工作脚本加载 HIP，向 `parm_node` 设置参数，对 `cook_node` 执行 cook
4. 返回执行结果和状态信息

## 四、技术方案详解

### 1. 前端画板 (Piskel)

*   **功能**：提供直观的地牢图编辑界面
*   **数据格式**：支持二值图片（黑白像素）和二维数组（0/1矩阵）
*   **交互**：添加控制按钮，支持地图编辑和导出
*   **技术栈**：JavaScript + HTML + CSS

### 2. 数据格式

*   **记录像素颜色的json**：
    *   黑色像素：非活动区
    *   红色像素：活动区域
    *   其他颜色：桥梁或者临时替代之用

### 3. 通信机制

*   **导出方式**：画板将当前地牢图导出为图片或矩阵
*   **传输协议**：本地HTTP请求
*   **数据格式**：JSON + 二进制图片数据

#### 3.1 调度-工作者（Dispatcher-Worker）方案

- **核心思想**：常驻的调度 HTTP 服务只负责接收请求与调度执行；真正的 Houdini 执行由每次请求启动的 hython 子进程完成，做到“请求即执行，进程即释放”。
- **优点**：
  - **隔离性强**：每次执行独立进程，互不影响，避免状态污染
  - **部署简单**：调度服务只依赖系统 Python + Flask；Houdini 相关依赖在 hython 进程内
  - **灵活传参**：请求时动态指定 hip、node 和参数

##### 流程
1. 前端/调用方向调度服务发送 `POST /cook`
2. 调度服务读取请求体：`hip`、`cook_node`（必须）、`parm_node`（可选，默认与 cook_node 相同）、`parms`（键值对）、可选 `hython` 或 `hfs`
3. 调度服务生成临时 `job.json`，启动 hython 子进程执行工作脚本 `hython_cook_worker.py`
4. 工作脚本在 hython 内：加载 HIP → 获取 cook_node 和 parm_node → 向 parm_node 设置参数 → 对 cook_node 执行 `cook(force=True)` → 输出规范化 JSON 到 stdout
5. 调度服务收集 stdout/stderr/exit code，合并耗时信息并返回给调用方

##### 接口
- **健康检查**：`GET /ping`
  - 返回：`{"status":"ok"}`
- **执行 cook**：`POST /cook`
  - 请求体（JSON）：
```json
{
  "hip": "C:/path/to/file.hip",
  "cook_node": "/obj/geo1/OUT",                    # 必须：要执行 cook 的节点
  "parm_node": "/obj/geo1/INPUT",                  # 可选：要设置参数的节点（默认与 cook_node 相同）
  "parms": { "seed": 3, "json_data": "{...}" },
  "hython": "C:/Program Files/Side Effects Software/Houdini 19.5.716/bin/hython.exe",
  "hfs": "C:/Program Files/Side Effects Software/Houdini 19.5.716",
  "timeout_sec": 600
}
```
  - 说明：优先使用 `hython` 字段；若未提供则尝试从 `hfs` 推断；都未提供则报错。`parms` 为节点参数字典（标量或 tuple/数组）。`cook_node` 是必须的，`parm_node` 是可选的，如果未提供则默认与 `cook_node` 相同。
  - 成功响应（示例）：
```json
{
  "ok": true,
  "cook_node": "/obj/geo1/OUT",
  "parm_node": "/obj/geo1/INPUT",
  "elapsed_ms": 245,
  "node_errors": [],
  "missing_parms": [],
  "elapsed_ms_dispatch": 312
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

##### 约定
- **hython 解析**：
  - 有 `hython` → 直接使用
  - 无 `hython` 且有 `hfs`/环境变量 `HFS` → 组合 `${HFS}/bin/hython.exe`
- **参数设置**：
  - 工作脚本会依次尝试 `parm.set(value)` 与 `parmTuple.set([...])`
  - 找不到的参数返回在 `missing_parms`
- **超时**：默认 600s，可在请求体 `timeout_sec` 指定

### 4. 本地Python脚本

*   **功能**：接收前端请求、解析数据、调用Houdini
*   **核心组件**：
    *   **HTTP 调度服务**（Dispatcher）：常驻 Flask 服务，接收 `hip/cook_node/parm_node/parms` 并启动 hython 子进程
    *   **hython 工作脚本**（Worker）：在 hython 内加载 HIP、向 parm_node 设置参数、对 cook_node 执行 `cook`
    *   图像处理模块
    *   Houdini调用接口
    *   结果返回处理

### 5. Houdini处理

*   **输入**：解析后的地牢图片/矩阵
*   **处理**：基于HDA文件进行地图生成和优化
*   **输出**：新的地牢数据（图片或矩阵格式）

### 6. 结果返回

*   **数据流**：Python脚本将Houdini生成的结果返回给前端
*   **画板更新**：自动刷新显示新生成的地牢图
*   **迭代支持**：用户可继续编辑或触发下一轮生成

## 五、安装和使用

### 1.环境要求

*   Node.js 和 npm
*   Python 3.7+
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
*   powershell发送伪请求，测试Houdini执行结果，例如：
```powershell
$body = @{
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
*   调整通信接口：` PcgPreferencesController.js`文件中的url，例如：`http://127.0.0.1:5050/cook `


### 3.使用方法

*   [ ] 待补充

## 开发计划

### 第一阶段-数值通信

*   [x] 基础画板功能
*   [x] demo_test.hip测试工程
*   [x] Python后端服务开发：后端参数接受与hip调用执行
*   [ ] 画板的参数发送功能

### 第二阶段

*   [ ] 数据格式标准化
*   [ ] 错误处理和日志系统
*   [ ] 用户界面优化

### 第三阶段

*   [ ] 高级地牢生成算法
*   [ ] 批量处理功能
*   [ ] 性能优化

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