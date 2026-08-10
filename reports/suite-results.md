# Kết quả suite

Sinh bởi `probe suite`. Đừng sửa tay — chạy lại là mất.

`ok=46`  `upstream_client_error=22`  `upstream_server_error=2`  `forbidden=1`  `upstream_timeout=1`

| route | case | payload | status | outcome | answered by | bytes | ms |
|---|---|---|---|---|---|---|---|
| `products-search` | long-string | `long-1k` | 200 | ok | upstream | 30 | 28 |
| `products-search` | long-string | `long-10k` | 200 | ok | upstream | 30 | 9 |
| `products-search` | long-string | `long-unicode-2k` | 200 | ok | upstream | 30 | 10 |
| `products-search` | special-chars | `special-ascii` | 200 | ok | upstream | 30 | 23 |
| `products-search` | special-chars | `special-quotes` | 500 | upstream_server_error | upstream | 1084 | 20 |
| `products-search` | special-chars | `special-whitespace` | 200 | ok | upstream | 30 | 8 |
| `products-search` | special-chars | `unicode-emoji` | 200 | ok | upstream | 30 | 10 |
| `products-search` | special-chars | `unicode-rtl` | 200 | ok | upstream | 30 | 8 |
| `products-search` | special-chars | `unicode-zero-width` | 200 | ok | upstream | 30 | 7 |
| `products-search` | special-chars | `unicode-combining` | 200 | ok | upstream | 30 | 12 |
| `products-search` | empty | `empty-string` | 200 | ok | upstream | 16578 | 15 |
| `products-search` | empty | `null` | 200 | ok | upstream | 16578 | 9 |
| `products-search` | empty | `whitespace-only` | 200 | ok | upstream | 30 | 9 |
| `products-search` | wrong-type | `wrong-type-int` | 200 | ok | upstream | 30 | 6 |
| `products-search` | wrong-type | `wrong-type-float` | 200 | ok | upstream | 30 | 8 |
| `products-search` | wrong-type | `wrong-type-bool` | 200 | ok | upstream | 442 | 5 |
| `products-search` | boundary | `boundary-zero` | 200 | ok | upstream | 8785 | 8 |
| `products-search` | boundary | `boundary-negative` | 200 | ok | upstream | 703 | 6 |
| `products-search` | boundary | `boundary-int64` | 200 | ok | upstream | 30 | 6 |
| `products-search` | boundary | `boundary-float-max` | 200 | ok | upstream | 30 | 25 |
| `products` | baseline | `-` | 200 | ok | upstream | 16026 | 32 |
| `app-version` | baseline | `-` | 200 | ok | upstream | 20 | 12 |
| `login` | long-string | `long-1k` | 401 | upstream_client_error | upstream | 26 | 21 |
| `login` | long-string | `long-10k` | 401 | upstream_client_error | upstream | 26 | 19 |
| `login` | long-string | `long-unicode-2k` | 401 | upstream_client_error | upstream | 26 | 20 |
| `login` | special-chars | `special-ascii` | 401 | upstream_client_error | upstream | 26 | 18 |
| `login` | special-chars | `special-quotes` | 500 | upstream_server_error | upstream | 1449 | 20 |
| `login` | special-chars | `special-whitespace` | 401 | upstream_client_error | upstream | 26 | 18 |
| `login` | special-chars | `unicode-emoji` | 401 | upstream_client_error | upstream | 26 | 21 |
| `login` | special-chars | `unicode-rtl` | 401 | upstream_client_error | upstream | 26 | 19 |
| `login` | special-chars | `unicode-zero-width` | 401 | upstream_client_error | upstream | 26 | 21 |
| `login` | special-chars | `unicode-combining` | 401 | upstream_client_error | upstream | 26 | 19 |
| `login` | empty | `empty-string` | 401 | upstream_client_error | upstream | 26 | 22 |
| `login` | empty | `null` | 401 | upstream_client_error | upstream | 26 | 20 |
| `login` | empty | `whitespace-only` | 401 | upstream_client_error | upstream | 26 | 5 |
| `login` | wrong-type | `wrong-type-int` | 401 | upstream_client_error | upstream | 26 | 14 |
| `login` | wrong-type | `wrong-type-float` | 401 | upstream_client_error | upstream | 26 | 21 |
| `login` | wrong-type | `wrong-type-bool` | 401 | upstream_client_error | upstream | 26 | 18 |
| `login` | wrong-type | `wrong-type-list` | 401 | upstream_client_error | upstream | 26 | 21 |
| `login` | wrong-type | `wrong-type-object` | 401 | upstream_client_error | upstream | 26 | 20 |
| `login` | boundary | `boundary-zero` | 401 | upstream_client_error | upstream | 26 | 23 |
| `login` | boundary | `boundary-negative` | 401 | upstream_client_error | upstream | 26 | 21 |
| `login` | boundary | `boundary-int64` | 401 | upstream_client_error | upstream | 26 | 17 |
| `login` | boundary | `boundary-float-max` | 401 | upstream_client_error | upstream | 26 | 20 |
| `metrics` | baseline | `-` | 403 | forbidden | gateway | 69 | 6 |
| `echo` | long-string | `long-1k` | 200 | ok | upstream | 1645 | 12 |
| `echo` | long-string | `long-10k` | 200 | ok | upstream | 10622 | 11 |
| `echo` | long-string | `long-unicode-2k` | 200 | ok | upstream | 5110 | 13 |
| `echo` | special-chars | `special-ascii` | 200 | ok | upstream | 187 | 11 |
| `echo` | special-chars | `special-quotes` | 200 | ok | upstream | 141 | 10 |
| `echo` | special-chars | `special-whitespace` | 200 | ok | upstream | 152 | 10 |
| `echo` | special-chars | `unicode-emoji` | 200 | ok | upstream | 173 | 7 |
| `echo` | special-chars | `unicode-rtl` | 200 | ok | upstream | 171 | 10 |
| `echo` | special-chars | `unicode-zero-width` | 200 | ok | upstream | 151 | 11 |
| `echo` | special-chars | `unicode-combining` | 200 | ok | upstream | 734 | 10 |
| `echo` | empty | `empty-string` | 200 | ok | upstream | 133 | 9 |
| `echo` | empty | `null` | 200 | ok | upstream | 135 | 13 |
| `echo` | empty | `whitespace-only` | 200 | ok | upstream | 139 | 10 |
| `echo` | wrong-type | `wrong-type-int` | 200 | ok | upstream | 137 | 10 |
| `echo` | wrong-type | `wrong-type-float` | 200 | ok | upstream | 133 | 9 |
| `echo` | wrong-type | `wrong-type-bool` | 200 | ok | upstream | 135 | 10 |
| `echo` | wrong-type | `wrong-type-list` | 200 | ok | upstream | 150 | 8 |
| `echo` | wrong-type | `wrong-type-object` | 200 | ok | upstream | 168 | 11 |
| `echo` | boundary | `boundary-zero` | 200 | ok | upstream | 129 | 10 |
| `echo` | boundary | `boundary-negative` | 200 | ok | upstream | 131 | 9 |
| `echo` | boundary | `boundary-int64` | 200 | ok | upstream | 165 | 7 |
| `echo` | boundary | `boundary-float-max` | 200 | ok | upstream | 139 | 5 |
| `slow` | under-timeout | `-` | 200 | ok | upstream | 16 | 221 |
| `slow` | over-timeout | `-` | 504 | upstream_timeout | gateway | 70 | 5013 |
| `big` | under-client-cap | `-` | 200 | ok | upstream | 4096 | 12 |
| `big` | over-client-cap | `-` | 200 | ok | upstream | 64000 | 12 |
| `status` | baseline | `-` | 418 | upstream_client_error | upstream | 17 | 11 |
