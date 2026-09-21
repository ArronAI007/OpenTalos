"""对应 packages/postgres-checkpoint/src/store.ts。"""

from datetime import UTC, datetime

from sqlalchemy import and_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from opentalos.checkpoint.schema import checkpoints_table
from opentalos.core_types import Checkpoint, CheckpointQuery


def _to_iso_z(dt: datetime) -> str:
    """Match InMemoryCheckpointStore's ISO format exactly (a trailing Z, not +00:00) so
    round-tripping a Checkpoint through either store implementation produces the same string."""
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _row_to_checkpoint(row) -> Checkpoint:
    return Checkpoint(
        graph_id=row.graph_id,
        run_id=row.run_id,
        tenant_id=row.tenant_id,
        session_id=row.session_id,
        node_cursor=row.node_cursor,
        state=row.state,
        pending_yields=row.pending_yields,
        status=row.status,
        created_at=_to_iso_z(row.created_at),
        cancel_requested=row.cancel_requested,
        steer_message=row.steer_message,
        error=row.error,
    )


class PostgresCheckpointStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def save(self, checkpoint: Checkpoint) -> None:
        async with self._engine.begin() as conn:
            # 事务级别设置 RLS 会话变量（is_local=true 的第三个参数），供数据库层 RLS 策略使用；
            # 应用层这里已经用 tenant_id 过滤，这一步是纵深防御，即使有一天某处查询忘了自己过滤，
            # 数据库策略也能兜底。
            await conn.execute(
                text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                {"tenant_id": checkpoint.tenant_id},
            )
            values = {
                "run_id": checkpoint.run_id,
                "graph_id": checkpoint.graph_id,
                "tenant_id": checkpoint.tenant_id,
                "session_id": checkpoint.session_id,
                "node_cursor": checkpoint.node_cursor,
                "state": checkpoint.state,
                "pending_yields": checkpoint.pending_yields,
                "status": checkpoint.status,
                "cancel_requested": checkpoint.cancel_requested,
                "steer_message": checkpoint.steer_message,
                "error": checkpoint.error,
                "created_at": datetime.fromisoformat(checkpoint.created_at.replace("Z", "+00:00")),
            }
            stmt = insert(checkpoints_table).values(**values)
            stmt = stmt.on_conflict_do_update(
                index_elements=[checkpoints_table.c.run_id],
                # 有意排除 cancel_requested/steer_message：这两个字段只能由 request_cancel()/
                # request_steer() 写，普通 save() 落盘绝不能碰它们，否则会和一个并发的取消/接话请
                # 求产生竞态（引擎自己拿着过时的内存值再存一次，把刚设置的请求悄悄清空）。
                set_={
                    "graph_id": stmt.excluded.graph_id,
                    "tenant_id": stmt.excluded.tenant_id,
                    "session_id": stmt.excluded.session_id,
                    "node_cursor": stmt.excluded.node_cursor,
                    "state": stmt.excluded.state,
                    "pending_yields": stmt.excluded.pending_yields,
                    "status": stmt.excluded.status,
                    "error": stmt.excluded.error,
                    "updated_at": text("now()"),
                },
                # 已存在的行如果是 failed，只有传入值本身也是 failed 时才允许更新——否则整条 UPDATE
                # 直接跳过（不执行），保护"一旦失败就是终态"这个不变量。裸列名（不带 excluded 前缀）
                # 解析为已存在行的当前值。
                where=(checkpoints_table.c.status != "failed") | (stmt.excluded.status == "failed"),
            )
            await conn.execute(stmt)

    async def load(self, run_id: str) -> Checkpoint | None:
        async with self._engine.connect() as conn:
            result = await conn.execute(select(checkpoints_table).where(checkpoints_table.c.run_id == run_id))
            row = result.first()
            return _row_to_checkpoint(row) if row else None

    async def list_checkpoints(self, query: CheckpointQuery) -> list[Checkpoint]:
        conditions = []
        if query.tenant_id:
            conditions.append(checkpoints_table.c.tenant_id == query.tenant_id)
        if query.session_id:
            conditions.append(checkpoints_table.c.session_id == query.session_id)
        stmt = select(checkpoints_table)
        if conditions:
            stmt = stmt.where(and_(*conditions))
        async with self._engine.connect() as conn:
            result = await conn.execute(stmt)
            return [_row_to_checkpoint(row) for row in result]

    async def request_cancel(self, run_id: str) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                update(checkpoints_table).where(checkpoints_table.c.run_id == run_id).values(cancel_requested=True)
            )

    async def request_steer(self, run_id: str, message: str) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                update(checkpoints_table).where(checkpoints_table.c.run_id == run_id).values(steer_message=message)
            )

    async def clear_steer_message(self, run_id: str) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                update(checkpoints_table).where(checkpoints_table.c.run_id == run_id).values(steer_message=None)
            )

    async def load_for_tenant(self, run_id: str, tenant_id: str) -> Checkpoint | None:
        async with self._engine.begin() as conn:
            await conn.execute(text("SELECT set_config('app.tenant_id', :tenant_id, true)"), {"tenant_id": tenant_id})
            result = await conn.execute(
                select(checkpoints_table).where(
                    and_(checkpoints_table.c.run_id == run_id, checkpoints_table.c.tenant_id == tenant_id)
                )
            )
            row = result.first()
            return _row_to_checkpoint(row) if row else None

    async def request_cancel_for_tenant(self, run_id: str, tenant_id: str) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(text("SELECT set_config('app.tenant_id', :tenant_id, true)"), {"tenant_id": tenant_id})
            await conn.execute(
                update(checkpoints_table)
                .where(and_(checkpoints_table.c.run_id == run_id, checkpoints_table.c.tenant_id == tenant_id))
                .values(cancel_requested=True)
            )

    async def request_steer_for_tenant(self, run_id: str, message: str, tenant_id: str) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(text("SELECT set_config('app.tenant_id', :tenant_id, true)"), {"tenant_id": tenant_id})
            await conn.execute(
                update(checkpoints_table)
                .where(and_(checkpoints_table.c.run_id == run_id, checkpoints_table.c.tenant_id == tenant_id))
                .values(steer_message=message)
            )

    async def clear_steer_message_for_tenant(self, run_id: str, tenant_id: str) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(text("SELECT set_config('app.tenant_id', :tenant_id, true)"), {"tenant_id": tenant_id})
            await conn.execute(
                update(checkpoints_table)
                .where(and_(checkpoints_table.c.run_id == run_id, checkpoints_table.c.tenant_id == tenant_id))
                .values(steer_message=None)
            )
