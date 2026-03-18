from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(slots=True)
class TokenCheckDependencies:
    """账号巡检用例依赖。

    说明：当前底层实现仍复用 legacy main.py 中的辅助函数，但巡检编排逻辑已
    正式下沉到 application 层，避免 container 直接反向 import main。
    """

    prepare_artifacts: Callable[[], None]
    load_local_accounts_for_check: Callable[[str], tuple[str, list[dict[str, Any]]]]
    build_check_account_record: Callable[[dict[str, Any], int], dict[str, Any] | None]
    check_one_local_account: Callable[..., dict[str, Any]]
    delete_remote_sub2api_account: Callable[[str], dict[str, Any]]
    delete_remote_cliproxyapi_file: Callable[[str], dict[str, Any]]
    delete_local_service_files: Callable[[str], dict[str, Any]]
    remove_local_account_from_accounts_file: Callable[[str, str, str], dict[str, Any]]
    resolve_report_path: Callable[[str], str]
    service_token_filename: Callable[[str], str]
    write_json: Callable[[str, dict[str, Any]], None]
    print_fn: Callable[[str], None]
    sleep: Callable[[float], None]
    proxy_pool: list[str]
    token_check_sleep: float = 0.0


@dataclass(slots=True)
class MaintainAccountsDependencies:
    """保号用例依赖。"""

    prepare_artifacts: Callable[[], None]
    token_check_use_case: "TokenCheckUseCase"
    count_local_accounts: Callable[[str], dict[str, Any]]
    run_batch: Callable[..., dict[str, Any]]
    print_fn: Callable[[str], None]
    sleep: Callable[[float], None]
    random_uniform: Callable[[float, float], float]
    artifact_output_file: str
    retry_limit: int = 0
    wait_min_seconds: float = 0.0
    wait_max_seconds: float = 0.0


@dataclass(slots=True)
class TokenCheckUseCase:
    """本地账号巡检用例。"""

    deps: TokenCheckDependencies

    def execute(self, input_path: str = "", report_path: str = "") -> dict[str, Any]:
        self.deps.prepare_artifacts()
        check_input_path, raw_accounts = self.deps.load_local_accounts_for_check(input_path)
        report_output_path = self.deps.resolve_report_path(report_path)

        if not raw_accounts:
            result = {
                "ok": False,
                "reason": "no_accounts_found",
                "input_path": check_input_path,
                "report_path": report_output_path,
                "summary": {"total": 0, "ok": 0, "deactivated_401": 0, "kept": 0, "deleted": 0, "request_error": 0},
                "items": [],
            }
            self.deps.write_json(report_output_path, result)
            return result

        accounts = []
        for idx, entry in enumerate(raw_accounts, start=1):
            item = self.deps.build_check_account_record(entry, idx)
            if item:
                accounts.append(item)

        proxies = [str(p).strip() for p in (self.deps.proxy_pool or []) if str(p).strip()]
        items: list[dict[str, Any]] = []
        summary = {
            "total": len(accounts),
            "ok": 0,
            "deactivated_401": 0,
            "kept": 0,
            "deleted": 0,
            "request_error": 0,
        }

        self.deps.print_fn(f"[TokenCheck] 开始巡检，共 {len(accounts)} 个账号")
        self.deps.print_fn(f"[TokenCheck] 数据源: {check_input_path}")
        self.deps.print_fn(f"[TokenCheck] 代理池: {proxies if proxies else '无(直连)'}")

        for idx, account in enumerate(accounts, start=1):
            proxy_url = proxies[(idx - 1) % len(proxies)] if proxies else ""
            check_result = self.deps.check_one_local_account(account, proxy_url=proxy_url)

            row = {
                "index": idx,
                "email": account["email"],
                "account_id": account["account_id"],
                "status": check_result["status"],
                "proxy": proxy_url,
                "reason": check_result["reason"],
                "should_delete": check_result["should_delete"],
                "response_excerpt": (check_result.get("response_text") or "")[:300],
                "local_cleanup": None,
                "sub2api_delete": None,
                "cliproxyapi_delete": None,
                "local_files_delete": None,
            }

            if check_result["ok"]:
                summary["ok"] += 1
                summary["kept"] += 1
            elif check_result["should_delete"]:
                summary["deactivated_401"] += 1
                row["sub2api_delete"] = self.deps.delete_remote_sub2api_account(account["email"])
                row["cliproxyapi_delete"] = self.deps.delete_remote_cliproxyapi_file(
                    self.deps.service_token_filename(account["email"])
                )
                row["local_files_delete"] = self.deps.delete_local_service_files(account["email"])
                row["local_cleanup"] = self.deps.remove_local_account_from_accounts_file(
                    account["email"],
                    account["account_id"],
                    check_input_path,
                )
                summary["deleted"] += 1
            else:
                summary["kept"] += 1
                if check_result["status"] == 0:
                    summary["request_error"] += 1

            items.append(row)
            self.deps.print_fn(
                f"[TokenCheck] [{idx}/{len(accounts)}] email={account['email']} status={check_result['status']} "
                f"delete={'yes' if check_result['should_delete'] else 'no'} proxy={proxy_url or '直连'}"
            )

            if self.deps.token_check_sleep > 0:
                self.deps.sleep(self.deps.token_check_sleep)

        result = {
            "ok": True,
            "input_path": check_input_path,
            "report_path": report_output_path,
            "summary": summary,
            "items": items,
        }
        self.deps.write_json(report_output_path, result)
        self.deps.print_fn("[TokenCheck] 巡检完成")
        return result


@dataclass(slots=True)
class MaintainAccountsUseCase:
    """持续保号用例。"""

    deps: MaintainAccountsDependencies

    def execute(
        self,
        *,
        target_total: int,
        max_workers: int,
        proxy_pool=None,
        check_input_path: str = "",
        report_path: str = "",
    ) -> dict[str, Any]:
        self.deps.prepare_artifacts()
        cleanup_result = self.deps.token_check_use_case.execute(input_path=check_input_path, report_path=report_path)
        local_state = self.deps.count_local_accounts(check_input_path)
        current_count = int(local_state["count"])
        target_total = max(0, int(target_total or 0))
        before_register_count = current_count
        deficit = max(0, target_total - current_count)

        register_attempts: list[dict[str, Any]] = []
        attempt_round = 0
        while deficit > 0:
            attempt_round += 1
            self.deps.print_fn(
                f"[Maintain] 当前本地有效账号 {current_count} 个，低于目标 {target_total}，开始第 {attempt_round} 次补注册，缺口 {deficit} 个"
            )
            attempt_result = self.deps.run_batch(
                total_accounts=deficit,
                output_file=self.deps.artifact_output_file,
                max_workers=max_workers,
                proxy_pool=proxy_pool,
            )
            register_attempts.append(attempt_result)

            local_state = self.deps.count_local_accounts(check_input_path)
            current_count = int(local_state["count"])
            deficit = max(0, target_total - current_count)
            if deficit <= 0:
                break

            if self.deps.retry_limit > 0 and attempt_round >= self.deps.retry_limit:
                self.deps.print_fn(f"[Maintain] 已达到补注册重试上限 {self.deps.retry_limit}，本轮停止")
                break

            wait_s = self.deps.random_uniform(self.deps.wait_min_seconds, self.deps.wait_max_seconds) if self.deps.wait_max_seconds > 0 else 0
            self.deps.print_fn(f"[Maintain] 仍缺少 {deficit} 个账号，等待 {wait_s:.1f}s 后继续补注册")
            if wait_s > 0:
                self.deps.sleep(wait_s)

        if not register_attempts:
            self.deps.print_fn(f"[Maintain] 当前本地有效账号 {current_count} 个，已达到目标 {target_total}，无需补注册")

        register_result = {
            "ok": all(item.get("ok") for item in register_attempts) if register_attempts else True,
            "attempts": register_attempts,
            "total": sum(int(item.get("total", 0) or 0) for item in register_attempts),
            "success": sum(int(item.get("success", 0) or 0) for item in register_attempts),
            "fail": sum(int(item.get("fail", 0) or 0) for item in register_attempts),
            "elapsed": sum(float(item.get("elapsed", 0) or 0) for item in register_attempts),
            "output_file": self.deps.artifact_output_file,
            "error": "" if not register_attempts else "; ".join([str(item.get("error") or "") for item in register_attempts if item.get("error")]),
        }

        final_state = self.deps.count_local_accounts(check_input_path)
        final_count = int(final_state["count"])
        ok = final_count >= target_total
        return {
            "ok": ok,
            "target_total": target_total,
            "before_register_count": before_register_count,
            "after_register_count": final_count,
            "registered_deficit": deficit,
            "cleanup": cleanup_result,
            "register": register_result,
            "local_accounts_path": final_state["path"],
        }
