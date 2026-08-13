# 优质代码分析示例

本示例校准分析层次和信息密度，不规定所有结果的篇幅。

## 输入代码

```python
from fastapi import FastAPI, Header, HTTPException
from httpx import AsyncClient

AUTH_URL = "https://auth.example.test/verify"
app = FastAPI()
client = AsyncClient()

async def fetch_user(token: str):
    response = await client.post(
        AUTH_URL,
        headers={"Authorization": f"Bearer {token}"},
        timeout=5,
    )
    if response.status_code != 200:
        return None
    return response.json()

def can_read(user: dict) -> bool:
    return user.get("active") and "article:read" in user.get("permissions", [])

@app.get("/articles/{article_id}")
async def get_article(article_id: str, authorization: str = Header()):
    token = authorization.removeprefix("Bearer ").strip()
    user = await fetch_user(token)
    if not user or not can_read(user):
        raise HTTPException(status_code=403, detail="Forbidden")
    return {"article_id": article_id}
```

## 示例输出

# 一句话说明

这段代码提供一个受权限保护的文章查询入口：根据请求凭证获取用户并校验读取权限，通过后返回文章标识。

# 核心流程

1. **接收文章请求**：FastAPI 调用 `get_article()`，由此进入当前片段的主路径。
2. **提取认证凭证**：入口从 `Authorization` Header 中取出 Token，交给身份查询使用。
3. **获取用户身份**：`fetch_user()` 请求认证地址，非 200 响应提前转为 `None`。
4. **校验读取权限**：`can_read()` 确认用户启用且拥有 `article:read` 权限，否则返回 403。
5. **返回文章标识**：鉴权通过后返回 `article_id`；当前片段没有读取文章正文。

主调用链：

```text
GET /articles/{article_id}
→ get_article()
→ fetch_user()
→ can_read()
→ 返回 article_id 或 403
```

# 代码详细分析

## 文件模块地图

| 模块 | 代码范围 | 作用 |
| --- | --- | --- |
| 依赖与共享对象 | L1-L6 | 准备 Web 入口、HTTP Client 和认证地址 |
| 用户获取与权限判断 | L8-L19 | 把 Token 转成用户并判断读取资格 |
| 文章请求入口 | L21-L27 | 串联凭证提取、鉴权和结果返回 |

## 模块一：依赖与共享对象

### L1-L6 — 准备运行依赖

```python
from fastapi import FastAPI, Header, HTTPException
from httpx import AsyncClient

AUTH_URL = "https://auth.example.test/verify"
app = FastAPI()
client = AsyncClient()
```

这里集中准备路由、请求头、HTTP 异常和异步请求能力，并创建后续代码复用的应用与 Client。当前片段能确认 `AUTH_URL` 用于认证请求，不能确认认证服务的内部实现。

## 模块二：用户获取与权限判断

### L8-L16 — 将 Token 转成用户

```python
async def fetch_user(token: str):
    response = await client.post(
        AUTH_URL,
        headers={"Authorization": f"Bearer {token}"},
        timeout=5,
    )
    if response.status_code != 200:
        return None
    return response.json()
```

L9-L13 是一次完整认证请求；地址、Header 和超时共同定义同一操作。非 200 响应结束当前路径并返回 `None`，成功时才把响应 JSON 交给调用方。

### L18-L19 — 汇总读取条件

```python
def can_read(user: dict) -> bool:
    return user.get("active") and "article:read" in user.get("permissions", [])
```

用户必须同时处于启用状态并拥有读取权限；缺少权限列表时使用空列表，因此判断结果为假。

## 模块三：文章请求入口

### L21-L27 — 串联完整请求路径

```python
@app.get("/articles/{article_id}")
async def get_article(article_id: str, authorization: str = Header()):
    token = authorization.removeprefix("Bearer ").strip()
    user = await fetch_user(token)
    if not user or not can_read(user):
        raise HTTPException(status_code=403, detail="Forbidden")
    return {"article_id": article_id}
```

路由装饰器让该函数由匹配的 GET 请求触发。入口依次完成 Token 提取、用户获取和权限判断；失败路径抛出 403，只有全部通过才返回文章标识。
