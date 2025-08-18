import asyncio

from app.platform.audit.logger import AuditEvent, AuditEventType, AuditLogger


def test_log_event_does_not_block_event_loop(tmp_path):
    async def run() -> None:
        db_path = tmp_path / "audit.db"
        logger = AuditLogger(str(db_path))

        events = [
            AuditEvent(
                event_type=AuditEventType.ACCESS_GRANTED,
                user_id=f"user{i}",
                resource_id=f"res{i}",
            )
            for i in range(100)
        ]

        loop = asyncio.get_running_loop()
        latencies: list[float] = []
        stop_event = asyncio.Event()

        async def monitor_latency() -> None:
            while not stop_event.is_set():
                start = loop.time()
                await asyncio.sleep(0.01)
                latencies.append(loop.time() - start - 0.01)

        monitor = asyncio.create_task(monitor_latency())
        await asyncio.gather(*(logger.log_event(e) for e in events))
        stop_event.set()
        await monitor
        await logger.close()

        assert max(latencies) < 0.1

    asyncio.run(run())
