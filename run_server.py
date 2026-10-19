"""一键启动可视化服务：python -X utf8 run_server.py，然后浏览器打开 http://127.0.0.1:8000"""
import uvicorn

if __name__ == "__main__":
    uvicorn.run("src.mv_proposal.server:app", host="127.0.0.1", port=8000)