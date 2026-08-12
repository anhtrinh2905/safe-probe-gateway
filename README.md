# api_gateway

Một **API Gateway** đặt trước hai ứng dụng thử nghiệm, và một **Python tool** chỉ
biết đúng một địa chỉ: gateway. Agent đề xuất request kiểm thử an toàn; gateway
quyết định request nào đi tiếp.

> Giá trị của repo này nằm ở chỗ **guardrail nằm ngoài tiến trình đang bị kiểm
> thử**. Tuần 3 đặt allowlist trong code của chính agent — cùng tiến trình với
> thứ đang đọc response của target vào prompt. Tuần 4 đẩy nó ra ngoài, và chứng
> minh bằng topology chứ không bằng lời.

---

## Bằng chứng ngắn nhất

```
$ curl --max-time 2 http://localhost:3000/
curl: (7) Failed to connect to localhost port 3000: Connection refused
```

Juice Shop đang chạy. Nó chỉ không có cổng nào ra host. Không có `ports:` trong
`docker-compose.yml`, và network của nó khai báo `internal: true`. "Mọi request
đều đi qua gateway" vì thế là một tính chất của môi trường, không phải một quy
ước mà tool được tin là sẽ tuân thủ.

Điều đó vẫn đúng kể cả khi `client.py` bị sửa để trỏ thẳng vào target, kể cả khi
có người chạy `curl` bằng tay, kể cả khi lớp LLM bị prompt-injection. Không cái
nào trong ba trường hợp đó có gì để kết nối tới.

---

## Kết quả

| | |
|---|---|
| Kiểm tra gateway bằng `curl` (`scripts/smoke.sh`) | **14 / 14 pass** |
| Request payload an toàn đã gửi (`probe suite`) | **72** |
| Test tự động | **112 pass** |
| Endpoint tuần 3 khai thác được, nay không tới được | **2** — `/ftp`, `/rest/basket/{id}` |
| API key xuất hiện trong log | **0** |

**Báo cáo đầy đủ:** [`reports/2026-08-14_TrinhThiLanAnh_Week4.md`](reports/2026-08-10_TrinhThiLanAnh_Track0.md)  
Khái niệm gateway viết lại bằng cách em hiểu: [`reports/cac_khai_niem.md`](reports/cac_khai_niem.md)  
Transcript từng mã lỗi: [`reports/evidence/`](reports/evidence/)

**Quan sát đáng chú ý:** payload `special-quotes` — đúng hai ký tự `"` và `'`,
không có `OR`, không có `UNION`, không có comment — làm `GET /rest/products/search`
trả **HTTP 500** kèm nguyên văn câu SQL trong `<title>`:

```
Error: SQLITE_ERROR: unrecognized token: ""'%') AND deletedAt IS NULL) ORDER BY name"
```

Tuần 3 đã kết luận endpoint này có SQL injection. Điều tuần 4 thêm vào: **cùng
một lớp lỗ hổng phát hiện được bằng payload không hề mang tính khai thác.** Xem
`reports/evidence/juice-shop-11-safe-payload-500.txt`.

---

## Kiến trúc

```
                     host
                      │
                      │  :8000   ← cổng duy nhất được publish
                ┌─────▼──────┐
   probe  ───►  │  gateway   │   key-auth · allowlist · ACL · rate limit
   (tool)       │            │   size cap · timeout · audit log
                └──┬──────┬──┘
       ┌───────────┘      └───────────┐
       │      network internal: true  │
  ┌────▼─────┐                  ┌─────▼────┐
  │juice-shop│                  │ lab-app  │
  │  :3000   │                  │  :8080   │
  └──────────┘                  └──────────┘
   không publish port            không publish port
```

**Hai target, hai vai trò.** Juice Shop là mục tiêu thật — nó là thứ tuần 3 tấn
công, và hai lỗ hổng tìm được ở đó nay nằm ngoài allowlist. `lab-app` (~80 dòng)
tồn tại để các *giới hạn* quan sát được thay vì suy ra: `/slow?ms=` để vượt
timeout, `/big?kb=` để vượt giới hạn kích thước, `/echo` để thấy payload tới nơi
nguyên vẹn.

---

## Repo này được tổ chức thế nào

| Thư mục | Chứa gì |
|---|---|
| `gateway/` | Gateway: `app.py` (generic) + `policy.yml` (**toàn bộ chính sách**) |
| `targets/lab-app/` | Ứng dụng nhỏ để chứng minh các giới hạn |
| `src/safe_probe/` | Python tool — stdlib-only |
| `scripts/` | `up.sh` `down.sh` `smoke.sh` `verify.sh` |
| `docs/` | **Quá trình**: phương pháp + 4 ADR |
| `data/` | **Output máy**: audit log của tool và của gateway — xoá được |
| `reports/` | **Kết quả**: báo cáo + bằng chứng + bảng suite |
| `tests/` | 112 test |

Ba ranh giới cần giữ:

1. **Chính sách nằm trong `policy.yml`, không nằm trong `app.py`.** Thấy một
   `if path == ...` trong code gateway là dấu hiệu chính sách đang rò rỉ.
2. **`src/safe_probe/` không được import `gateway/`.** Nếu tool đọc được policy,
   guardrail lại quay về trong tiến trình.
3. **`data/` vứt đi lúc nào cũng được.** Xoá nó không được làm mất công sức trí óc nào.

---

## Chạy

```bash
bash scripts/up.sh        # sinh API key vào .env, dựng gateway + 2 target,
                          # rồi tự kiểm tra rằng target không tới được từ host
bash scripts/smoke.sh     # 14 kiểm tra bằng curl -> reports/evidence/
bash scripts/verify.sh    # ruff + pytest + grep key + ggshield
bash scripts/down.sh
```

Tool:

```bash
PYTHONPATH=src python3 -m safe_probe.cli routes         # gateway công bố cái gì
PYTHONPATH=src python3 -m safe_probe.cli payloads       # catalogue payload an toàn

PYTHONPATH=src python3 -m safe_probe.cli get /api/Products
PYTHONPATH=src python3 -m safe_probe.cli get /ftp                          # -> blocked
PYTHONPATH=src python3 -m safe_probe.cli get /rest/products/search --payload long-10k
PYTHONPATH=src python3 -m safe_probe.cli post /rest/user/login \
    --field email --payload wrong-type-int --field-value password=nope -v

PYTHONPATH=src python3 -m safe_probe.cli suite          # toàn bộ catalogue x allowlist
PYTHONPATH=src python3 -m safe_probe.cli --no-client-limits get /ftp   # vẫn bị chặn
```

Lớp LLM (tuỳ chọn, cần `OPENCODE_API_KEY` trong `.env`):

```bash
PYTHONPATH=src python3 -m safe_probe.cli plan --goal "input validation" --rounds 2
```

> `smoke.sh` cố tình làm cạn rate bucket ở bước cuối. Chờ ~70 giây trước khi chạy
> `suite`, nếu không những request đầu sẽ nhận 429 — đúng như thiết kế, chỉ là
> không phải thứ đang muốn đo.

---

## Đọc theo thứ tự nào

1. `gateway/policy.yml` — toàn bộ bề mặt an ninh, 100 dòng, đọc hết trong một phút
2. `docker-compose.yml` — khối `networks` ở cuối là luận điểm chính
3. [`docs/adr/0003-topology-la-bang-chung.md`](docs/adr/0003-topology-la-bang-chung.md) — vì sao khối đó quan trọng hơn mọi thứ khác
4. [`docs/methodology.md`](docs/methodology.md) — bốn lớp kiểm soát, xếp từ yếu tới mạnh
5. [`reports/2026-08-10_TrinhThiLanAnh_Track0.md`](reports/2026-08-10_TrinhThiLanAnh_Track0.md) — báo cáo đầy đủ

## ADR

| | |
|---|---|
| [0001](docs/adr/0001-gateway-tu-viet.md) | Gateway tự viết thay vì Kong hoặc Nginx |
| [0002](docs/adr/0002-guardrail-hai-lop.md) | Guardrail hai lớp, và LLM chỉ được chọn hai định danh |
| [0003](docs/adr/0003-topology-la-bang-chung.md) | Target không publish port: topology là bằng chứng |
| [0004](docs/adr/0004-payload-an-toan-la-bat-bien.md) | "Payload an toàn" là bất biến có test |
