"""Custom tool package for the meeting assistant artifact.

RFC-0004: NAC 会务 Agent 制品与工具契约

This package implements the FastAPI-backed tools used by the NAC meeting
assistant. All business operations go through the FastAPI boundary defined in
RFC-0002; the tools never import SQLite repositories or domain services.
"""
