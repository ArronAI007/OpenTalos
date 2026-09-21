"""对应 packages/checkpoint/src/index.ts。"""

from opentalos.core_types import Checkpoint, CheckpointQuery


class InMemoryCheckpointStore:
    def __init__(self) -> None:
        self._checkpoints: dict[str, Checkpoint] = {}

    async def save(self, checkpoint: Checkpoint) -> None:
        existing = self._checkpoints.get(checkpoint.run_id)

        # 一旦某个 checkpoint 被记录为 "failed"（Worker 重试耗尽后的最终失败分支），这是一个终态、
        # 权威的决定——普通 save() 不能悄悄把它降级回 running/paused/done。这对超时触发的失败路径
        # 尤其重要：runWithTimeout() 会用 race 把节点执行和一个超时计时器赛跑，超时就中止，但原来
        # 的节点执行并没有被真正取消——它会在后台继续孤零零地跑。如果那个被遗弃的执行优雅处理了中
        # 止信号、正常结束（而不是抛异常），引擎会走到它平常的 completeNode() 路径，用一个完全正常
        # 的（非 failed）checkpoint 调用 save()。没有这层保护，这次过时的 save 就会落在（并悄悄覆
        # 盖掉）Worker 已经持久化的失败状态之后。"failed"→"failed" 的重新保存，或者传入状态本来就
        # 是 "failed" 的保存，仍然是合法的终态写入，要正常放行。
        if existing is not None and existing.status == "failed" and checkpoint.status != "failed":
            return

        # 保留当前已存储的 cancel_requested/steer_message 值（只由 request_cancel()/request_steer()
        # 在第一次 save 之后设置），而不是被传入 checkpoint 的对应字段盲目覆盖。引擎调用 save() 时
        # 用的是一个加载/创建一次后就不再中途刷新这两个字段的内存 Checkpoint 对象，所以如果直接整
        # 体替换，引擎下一次节点边界的 save() 落地时就会悄悄清掉一个并发的 request_cancel()/
        # request_steer()。只有在还没有任何行时（这个 run_id 的第一次 save），才用传入值做初始化。
        merged = checkpoint.model_copy(
            update={
                "cancel_requested": existing.cancel_requested if existing else checkpoint.cancel_requested,
                "steer_message": existing.steer_message if existing else checkpoint.steer_message,
            }
        )
        self._checkpoints[checkpoint.run_id] = merged

    async def load(self, run_id: str) -> Checkpoint | None:
        return self._checkpoints.get(run_id)

    async def list_checkpoints(self, query: CheckpointQuery) -> list[Checkpoint]:
        results = []
        for checkpoint in self._checkpoints.values():
            if query.tenant_id and checkpoint.tenant_id != query.tenant_id:
                continue
            if query.session_id and checkpoint.session_id != query.session_id:
                continue
            results.append(checkpoint)
        return results

    async def request_cancel(self, run_id: str) -> None:
        checkpoint = self._checkpoints.get(run_id)
        if checkpoint is not None:
            self._checkpoints[run_id] = checkpoint.model_copy(update={"cancel_requested": True})

    async def request_steer(self, run_id: str, message: str) -> None:
        checkpoint = self._checkpoints.get(run_id)
        if checkpoint is not None:
            self._checkpoints[run_id] = checkpoint.model_copy(update={"steer_message": message})

    async def clear_steer_message(self, run_id: str) -> None:
        checkpoint = self._checkpoints.get(run_id)
        if checkpoint is not None:
            self._checkpoints[run_id] = checkpoint.model_copy(update={"steer_message": None})

    async def load_for_tenant(self, run_id: str, tenant_id: str) -> Checkpoint | None:
        checkpoint = self._checkpoints.get(run_id)
        return checkpoint if checkpoint is not None and checkpoint.tenant_id == tenant_id else None

    async def request_cancel_for_tenant(self, run_id: str, tenant_id: str) -> None:
        checkpoint = self._checkpoints.get(run_id)
        if checkpoint is not None and checkpoint.tenant_id == tenant_id:
            self._checkpoints[run_id] = checkpoint.model_copy(update={"cancel_requested": True})

    async def request_steer_for_tenant(self, run_id: str, message: str, tenant_id: str) -> None:
        checkpoint = self._checkpoints.get(run_id)
        if checkpoint is not None and checkpoint.tenant_id == tenant_id:
            self._checkpoints[run_id] = checkpoint.model_copy(update={"steer_message": message})

    async def clear_steer_message_for_tenant(self, run_id: str, tenant_id: str) -> None:
        checkpoint = self._checkpoints.get(run_id)
        if checkpoint is not None and checkpoint.tenant_id == tenant_id:
            self._checkpoints[run_id] = checkpoint.model_copy(update={"steer_message": None})
