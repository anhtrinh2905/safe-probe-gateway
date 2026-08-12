# reports/

Thư mục này trả lời **"chứng minh được cái gì"**. "Làm thế nào và vì sao" nằm ở
[`docs/`](../docs/methodology.md).

| File | Là gì | Sửa tay được không |
| --- | --- | --- |
| [`2026-08-14_TrinhThiLanAnh_Week4.md`](2026-08-10_TrinhThiLanAnh_Track0.md) | **Báo cáo tuần 4** — đọc file này trước | Có |
| [`cac_khai_niem.md`](cac_khai_niem.md) | Khái niệm gateway viết lại bằng cách em hiểu | Có |
| [`suite-results.md`](suite-results.md) | Bảng 72 request payload an toàn | **Không** — sinh bởi `probe suite` |
| [`evidence/`](evidence/) | 17 transcript, sinh bởi `scripts/smoke.sh` và công cụ | **Không** |

---

## Kết quả một dòng mỗi ý

| | |
| --- | --- |
| Kiểm soát gateway chứng minh bằng `curl` | **14 / 14 pass** |
| Request payload an toàn đã gửi | **72** — 22 payload × 9 route |
| Request bị gateway từ chối trong phiên chạy | **97** |
| Test tự động | **112 pass** |
| Endpoint tuần 3 khai thác được, nay không tới được | **2** — `/ftp`, `/rest/basket/{id}` |
| Probe do LLM đề xuất / bị từ chối vì id không hợp lệ | **12 / 0** |
| API key xuất hiện trong nhật ký | **0** |

---

## Bảng bàn giao: mỗi yêu cầu ↔ một file

| Yêu cầu đề bài | Bằng chứng |
| --- | --- |
| API Gateway hoạt động | [`juice-shop-02-allowed-200.txt`](evidence/juice-shop-02-allowed-200.txt) |
| **Request đều đi qua gateway** | [`juice-shop-01`](evidence/juice-shop-01-no-direct-access.txt) · [`lab-app-01`](evidence/lab-app-01-no-direct-access.txt) |
| Endpoint bị cấm bị chặn | [`juice-shop-03`](evidence/juice-shop-03-blocked-ftp.txt) · [`04`](evidence/juice-shop-04-blocked-basket.txt) · [`05`](evidence/juice-shop-05-blocked-users.txt) |
| API key riêng cho công cụ | [`juice-shop-06`](evidence/juice-shop-06-no-key-401.txt) · [`07`](evidence/juice-shop-07-wrong-key-401.txt) |
| Chỉ endpoint trong allowlist | [`juice-shop-08`](evidence/juice-shop-08-method-405.txt) · [`09`](evidence/juice-shop-09-forbidden-403.txt) |
| Giới hạn số request mỗi phút | [`juice-shop-10`](evidence/juice-shop-10-rate-limit-429.txt) |
| Giới hạn thời gian chờ | [`lab-app-03`](evidence/lab-app-03-upstream-timeout-504.txt) |
| Giới hạn kích thước response | [`lab-app-04`](evidence/lab-app-04-response-truncated.txt) |
| Giới hạn kích thước request | [`lab-app-02`](evidence/lab-app-02-request-413.txt) |
| lab-app: auth / allowlist / proxy | [`lab-app-05`](evidence/lab-app-05-no-key-401.txt) · [`06`](evidence/lab-app-06-wrong-key-401.txt) · [`07`](evidence/lab-app-07-blocked-health-404.txt) · [`08`](evidence/lab-app-08-blocked-items-404.txt) · [`09`](evidence/lab-app-09-echo-allowed-200.txt) · [`10`](evidence/lab-app-10-status-418.txt) · [`11`](evidence/lab-app-11-rate-limit-429.txt) |
| Công cụ xử lý timeout & lỗi kết nối | `tests/test_client.py` |
| Chỉ dùng payload an toàn | [`suite-results.md`](suite-results.md) · `tests/test_payloads.py` |
| **Nhật ký không lưu API key** | [`gateway-01`](evidence/gateway-01-log-clean.txt) · `tests/test_redaction.py` |
| Agent đề xuất & gửi request | [`gateway-02`](evidence/gateway-02-llm-plan-run.json) |
| Lớp nào thực sự gánh việc | [`juice-shop-12`](evidence/juice-shop-12-no-client-limits-still-blocked.txt) |
| Quan sát ngoài dự kiến | [`juice-shop-11`](evidence/juice-shop-11-safe-payload-500.txt) |

---

## Sinh lại

```bash
bash scripts/up.sh        # dựng stack, tự kiểm tra topology
bash scripts/smoke.sh     # -> evidence/juice-shop-*, lab-app-*, gateway-01
sleep 70                  # smoke làm cạn rate bucket ở bước cuối
PYTHONPATH=src python3 -m safe_probe.cli suite    # -> suite-results.md
```

`juice-shop-11`, `juice-shop-12`, `gateway-02` sinh bằng công cụ (`probe get/post`,
`--no-client-limits`, `probe plan`) — lệnh cụ thể nằm ngay trong đầu mỗi file.
