import asyncio
from typing import Dict, Set
from loguru import logger
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

# 创建一个 FastAPI 实例
app = FastAPI()

# 挂载静态文件目录，将 "/static" 路径下的请求映射到 "static" 目录
app.mount("/static", StaticFiles(directory="static"), name="static")

class ConnectionManager:
    """连接管理器类，用于管理 WebSocket 连接和客户端之间的聊天关系。
    """
    def __init__(self):
        # 存储活跃连接，键为客户端 ID，值为 WebSocket 对象
        self.active_connections: Dict[int, WebSocket] = {}
        # 记录每个客户端正在聊天的对象，键为客户端 ID，值为正在聊天的目标客户端 ID 集合
        self.chat_pairs: Dict[int, Set[int]] = {}

    async def connect(self, websocket: WebSocket, client_id: int):
        """接受新的 WebSocket 连接，并将其添加到活跃连接字典中。
        Args:
            websocket: WebSocket 对象
            client_id: 客户端 ID
        """
        await websocket.accept()  # 接受 WebSocket 连接
        self.active_connections[client_id] = websocket  # 将该客户端的 WebSocket 连接存储到活跃连接字典中
        self.chat_pairs[client_id] = set()  # 初始化该客户端的聊天对象集合

    async def notify_target_disconnect(self, target_id: int, client_id: int):
        """通知目标客户端，对方已离开当前聊天。
        Args:
            target_id: 目标聊天的客户端 ID
            client_id: 客户端 ID
        Notes: 
        `asyncio.create_task`会把发送"离开"消息的任务集合到一起发送，有一定延迟性，所以使用时需要监测websockets连接状态。
        """
        try:
            await self.active_connections[target_id].send_text(f"--对方已离开当前聊天--")
        except WebSocketDisconnect:
            print(f"Target client {target_id} 已断开，无法通知对方 {client_id} 已离开。")
        except Exception as e:
            logger.error(f"通知目标客户端 {target_id} 失败，错误信息: {e}")


    def disconnect(self, client_id: int):
        """移除断开连接的客户端，并通知该客户端的聊天对象。
        Args:
            client_id: 客户端 ID
        """
        if client_id in self.active_connections:
            del self.active_connections[client_id]  # 从活跃连接字典中删除该客户端的连接
            # 通知与该客户端聊天的所有目标客户端
            for target_id in self.chat_pairs.get(client_id, []):
                if target_id in self.active_connections:
                    # 异步发送消息通知目标客户端
                    asyncio.create_task(self.notify_target_disconnect(target_id, client_id))

            # 从聊天关系字典中删除该客户端的记录
            del self.chat_pairs[client_id]

    async def send_personal_message(self, message: str, client_id: int):
        """发送私人消息给指定客户端。
        Args:
            message: 要发送的消息内容
            client_id: 目标客户端 ID
        """
        websocket = self.active_connections.get(client_id)
        if websocket:
            try:
                await websocket.send_text(message)  # 发送消息给目标客户端
            except WebSocketDisconnect:
                self.disconnect(client_id)  # 处理断开连接逻辑
            except Exception as e:
                logger.error(f"websocket连接失效，向client发送消息失败 {client_id}: {e}")

    def update_chat_pairs(self, client_id: int, target_id: int):
        """更新聊天关系，记录两个客户端之间的聊天关系。
        Args:
            client_id: 发起聊天的客户端 ID
            target_id: 目标聊天的客户端 ID
        """
        self.chat_pairs[client_id].add(target_id)  # 将目标客户端 ID 添加到发起客户端的聊天对象集合中
        if target_id in self.chat_pairs:
            self.chat_pairs[target_id].add(client_id)  # 反向添加发起客户端 ID 到目标客户端的聊天对象集合中

# 创建一个全局的连接管理器实例
manager = ConnectionManager()

@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: int):
    """
    WebSocket 端点，用于处理客户端的连接和消息传递。

    :param websocket: WebSocket 对象
    :param client_id: 客户端 ID
    """
    await manager.connect(websocket, client_id)  # 连接客户端
    try:
        while True:
            # 接收来自客户端的消息，格式为 "target_id:message"
            data = await websocket.receive_text()
            target_id, message = data.split(":", 1)  # 拆分目标 ID 和消息内容
            target_id = int(target_id)
            # 更新聊天对象对
            manager.update_chat_pairs(client_id, target_id)
            # 发送消息给指定的目标客户端
            await manager.send_personal_message(f"Client #{client_id} says: {message}", target_id)
    except WebSocketDisconnect:
        # 当客户端断开连接时，移除该连接并处理相关逻辑
        manager.disconnect(client_id)

@app.get("/", response_class=FileResponse)
async def read_root():
    """
    根路径处理函数，返回静态文件 "index.html"。

    :return: 返回 index.html 文件
    """
    return FileResponse("static/index.html")