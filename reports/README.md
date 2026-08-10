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
| API Gateway hoạt động | [`evidence/02-allowed-200.txt`](evidence/02-allowed-200.txt) |
| **Request đều đi qua gateway** | [`evidence/01-no-direct-access.txt`](evidence/01-no-direct-access.txt) |
| Endpoint bị cấm bị chặn | [`03`](evidence/03-blocked-ftp.txt) · [`04`](evidence/04-blocked-basket.txt) · [`05`](evidence/05-blocked-users.txt) |
| API key riêng cho công cụ | [`06`](evidence/06-no-key-401.txt) · [`07`](evidence/07-wrong-key-401.txt) |
| Chỉ endpoint trong allowlist | [`08`](evidence/08-method-405.txt) · [`09`](evidence/09-forbidden-403.txt) |
| Giới hạn số request mỗi phút | [`13`](evidence/13-rate-limit-429.txt) |
| Giới hạn thời gian chờ | [`11`](evidence/11-upstream-timeout-504.txt) |
| Giới hạn kích thước response | [`12`](evidence/12-response-truncated.txt) |
| Giới hạn kích thước request | [`10`](evidence/10-request-413.txt) |
| Công cụ xử lý timeout & lỗi kết nối | `tests/test_client.py` |
| Chỉ dùng payload an toàn | [`suite-results.md`](suite-results.md) · `tests/test_payloads.py` |
| **Nhật ký không lưu API key** | [`14`](evidence/14-gateway-log-clean.txt) · `tests/test_redaction.py` |
| Agent đề xuất & gửi request | [`17`](evidence/17-llm-plan-run.json) |
| Lớp nào thực sự gánh việc | [`16`](evidence/16-no-client-limits-still-blocked.txt) |
| Quan sát ngoài dự kiến | [`15`](evidence/15-safe-payload-500.txt) |

---

## Sinh lại

```bash
bash scripts/up.sh        # dựng stack, tự kiểm tra topology
bash scripts/smoke.sh     # -> evidence/01..14
sleep 70                  # smoke làm cạn rate bucket ở bước cuối
PYTHONPATH=src python3 -m safe_probe.cli suite    # -> suite-results.md
```

`evidence/15`, `16`, `17` sinh bằng công cụ (`probe get/post`, `--no-client-limits`,
`probe plan`) — lệnh cụ thể nằm ngay trong đầu mỗi file.
