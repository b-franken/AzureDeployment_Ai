import asyncio
import os


class AzCliError(RuntimeError):
    pass


class AzCli:
    async def what_if_group(
        self, resource_group: str, template_file: str, subscription_id: str | None
    ) -> str:
        args = [
            "az",
            "deployment",
            "group",
            "what-if",
            "--resource-group",
            resource_group,
            "--template-file",
            template_file,
            "--no-pretty-print",
            "--output",
            "json",
        ]
        if subscription_id:
            args.extend(["--subscription", subscription_id])
        return await self._run(args)

    async def deploy_group(
        self, resource_group: str, template_file: str, subscription_id: str | None
    ) -> str:
        args = [
            "az",
            "deployment",
            "group",
            "create",
            "--resource-group",
            resource_group,
            "--template-file",
            template_file,
            "--output",
            "json",
        ]
        if subscription_id:
            args.extend(["--subscription", subscription_id])
        return await self._run(args)

    async def _run(self, args: list[str]) -> str:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "AZURE_CORE_ONLY_SHOW_ERRORS": "1"},
        )
        out_b, err_b = await proc.communicate()
        out = out_b.decode("utf-8", errors="ignore")
        err = err_b.decode("utf-8", errors="ignore")
        if proc.returncode != 0:
            raise AzCliError(err or out or "az exited with non zero")
        return out
