# Test Raporu: Logistics AI Veri Ajanı (Faz 2)

Tarih: 2026-11-25. Durum değerleri: **PASS**, **FAIL**, **NOT TESTED**, **BLOCKED**.
Raporda şifre, token veya imza anahtarı yer almaz. Tüm sayılar bu oturumdaki gerçek çalıştırmalardan alınmıştır.

## Özet

| Bölüm | Kapsam | Sonuç |
| --- | --- | --- |
| A) Mock / yerel testler | `app/agent` 292, `streamlit_client` 61, `scripts` 19 test (AWS yok, bellek içi/sahte DynamoDB, betikli modeller) | 372 PASS, 0 FAIL |
| B) Yerel entegrasyon | moto DynamoDB + gerçek Bedrock çağrısı + `agentcore dev` + Streamlit | 12/12 adım PASS |
| C) Gerçek AWS entegrasyonu | Gerçek DynamoDB tabloları, AgentCore Runtime dağıtımı, Secrets Manager, SigV4 çağrısı | NOT TESTED (onay olmadan kaynak oluşturulmadı) |
| D) Gerçek LLM testleri | Bedrock Haiku 4.5, 98 vaka, 224 model çağrısı | Tüm metrikler %100 (istem düzeltmesinden sonra) |

- Bu çalıştırmada başarısız test çıkmadı. Düzeltilen eski hatalar E bölümünde listelenmiştir.
- Dağıtım (`agentcore deploy`), gerçek AWS kaynağı oluşturma ve `ingest --apply` (gerçek hesaba) yapılmadı.
- Bilinen riskler F bölümündedir. En önemlisi Açık Karar 1: `agentcore.json` hâlâ Cognito `CUSTOM_JWT` kullanıyor, dağıtılmış ortamda Faz 2 akışı bu haliyle çalışmaz.

## Ortam

| Öğe | Değer |
| --- | --- |
| İşletim sistemi / Python | Linux, Python 3.12 (agent `.venv`: 3.12; scripts `.venv`: 3.12.3) |
| Paket yöneticisi | uv; pytest 9.2.0 |
| Ajan | strands-agents 1.66.0, bedrock-agentcore 1.26.1, AgentCore CLI 1.0.3 |
| İstemci | streamlit 1.67.0 |
| Yerel DynamoDB | moto 5.2.6 (`moto_server`, 127.0.0.1:5001), boto3 1.44.11 (`AWS_ENDPOINT_URL_DYNAMODB` desteği) |
| Model | `global.anthropic.claude-haiku-4-5-20251001-v1:0` (us-east-1; `list-foundation-models` ile keşfedildi) |
| Operasyonel referans tarihi | 2026-11-24 (veri tarihi; sistem saatinden bağımsız, bkz. DS08-DS10) |
| Bağlantı noktaları | moto 5001, `agentcore dev` 8082, Streamlit 8501. 8080 (IDE) kullanılmadı. 8081 başka bir proje (`CustomerServiceAgent`) tarafından kullanıldığı için dokunulmadı, 8082'ye geçildi |
| Veri | `Data/Agent_AWS_2026-11-24.xlsx` (gerçek dosya, sürüm kontrolünde değil) |

Çalıştırma komutları:

```bash
cd app/agent && uv run pytest -q           # varsayılan: -m "not llm"
cd streamlit_client && uv run pytest -q
cd scripts && uv run pytest -q
cd app/agent && uv run pytest -m llm -q    # yalnızca gerçek Bedrock (maliyetli; yalnızca model çağırır)
```

---

## A) MOCK / yerel testler (AWS yok)

Bellek içi depolar, `fake DynamoDB`/`Stubber` ve betikli (mock) modeller kullanır. Gerçek AWS çağrısı yapılmaz.

### A.0 Paket sonuçları

| Paket | Komut | Toplanan | PASS | FAIL | Not |
| --- | --- | --- | --- | --- | --- |
| `app/agent` | `uv run pytest -q` | 391 | 292 | 0 | 99 test `llm` işaretli, varsayılan olarak hariç (bkz. D) |
| `streamlit_client` | `uv run pytest -q` | 61 | 61 | 0 | 10 test yerel mod içindir (`test_local_mode.py`) |
| `scripts` | `uv run pytest -q` | 19 | 19 | 0 | 12 test yerel tablo güvenlik kontrolleridir |
| **Toplam** | | **471** | **372** | **0** | 99 LLM testi D bölümünde |

### A.1 Test alanı 1: Veri kaynağı (`app/agent/tests/e2e/test_data_source.py`)

| Id | Beklenen | Gerçekleşen | Durum |
| --- | --- | --- | --- |
| DS01 `row_counts` | Gerçek Excel'deki operasyonel sheet satır sayıları (q1 46, q2 122, q3 199, q4 13, q5 9, summary_df 5, critical 131) | Eşleşti | PASS |
| DS02 `column_names_preserved` | Excel kolon adları (yazım hataları dahil) korunur | Korundu | PASS |
| DS03 `auth_sheets_never_in_repo` | `role_user` ve `permissions` kb deposuna girmez | Girmedi | PASS |
| DS04 `functions_sheet_matches_code` | `Functions` sheet'i (fonksiyon-tablo-Keyid) kodla birebir | Eşleşti | PASS |
| DS05 `json_columns_parse_and_keys` | JSON kolonları parse edilir, anahtarlar mevcut | Parse edildi | PASS |
| DS06 `keys_are_strings_without_dot_zero` | `shipment_id`, `materialno`, `mip`, `supplier_code` string, baştaki sıfır korunur, `.0` yok | Korundu | PASS |
| DS07 `bad_json_injection_does_not_crash` | Bozuk JSON enjeksiyonunda çökme yok, kayıt raporlanır | Çökmedi | PASS |
| DS08 `reference_date_is_data_date` | Referans tarih veri tarihi (2026-11-24) | Doğru | PASS |
| DS09 / DS09b `outputs_independent_of_system_clock` | Saat farklı tarihe sabitlenince `get_delayed_truck`, `get_critical_part_status`, Dashboard çıktısı değişmez | Değişmedi | PASS |
| DS10 `no_clock_used_for_delay_derivation` | Kodda `datetime.now`/`date.today` ile gecikme türetilmez | Türetilmiyor | PASS |
| DS11 `dashboard_kpis_match_summary_df` | KPI değerleri `summary_df` ile aynı | Aynı | PASS |
| DS12 `tools_return_real_rows` | Araçlar gerçek Excel satırlarını döndürür | Döndürdü | PASS |
| NLM_00 `dataset_size_and_real_keys` | NL veri kümesi boyutu ve Keyid'ler gerçek Excel'den | Doğru | PASS |

### A.2 Test alanı 2: Kimlik doğrulama (`test_auth_permissions.py`, `test_session_isolation.py`, `test_dashboard_ui.py`)

| Id | Beklenen | Gerçekleşen | Durum |
| --- | --- | --- | --- |
| AUTH_01 `successful_login_per_role` (4 parametre) | SUPPLIER, MATERIAL_RESPONSIBLE, TRANSPORT_OFFICE, ADMIN gerçek Excel kullanıcılarıyla girer | 4/4 giriş başarılı | PASS |
| AUTH_02 `passwords_stored_hashed_only` | Şifre yalnızca argon2id özeti olarak saklanır | Düz metin yok | PASS |
| AUTH_03 `wrong_password_identical_to_unknown_user` | Yanlış şifre ile bilinmeyen kullanıcı aynı genel hata | Aynı | PASS |
| AUTH_04 `inactive_user_cannot_login` | Pasif kullanıcı giremez | Girilemedi | PASS |
| AUTH_05 `invalid_token_rejected` (8 parametre) | Boş, 2 parçalı, yanlış imza, `alg=none`, HS384, değiştirilmiş yük reddedilir | 8/8 reddedildi | PASS |
| AUTH_06 `expired_token_rejected_after_30_min` | Sabit saatle 30 dk sonra token reddedilir | Reddedildi | PASS |
| AUTH_07 `logout_audit_and_session_cleared` | Logout denetim kaydı yazar, oturum temizlenir | Doğru | PASS |
| AUTH_08 / AUTH_09 | 5 hatadan sonra 15 dk kilit; kilit açıldıktan sonra sayaç yeniden başlar | Doğru | PASS |
| UI_02 / UI_03 / UI_04 / UI_05 | Rol başına giriş, yanlış şifrede genel hata, logout, oturum bitince giriş ekranı | Doğru | PASS |
| SESS_01-SESS_08 | 4 eşzamanlı oturum ayrı kimlik, geçmiş izolasyonu, başka token'la geçmişe erişilememe, rol claim'i ile yükselme yok, boşta zaman aşımı, pasif kullanıcı | Doğru | PASS |

### A.3 Test alanı 3: İzinler

| Id | Beklenen | Gerçekleşen | Durum |
| --- | --- | --- | --- |
| PERM_01 `initial_access_to_all_tables_and_functions` (4 rol) | Başlangıçta her rol tüm operasyonel tablo ve fonksiyonlara erişir | 4/4 | PASS |
| PERM_02 | `role_user`, `permissions` ve bilinmeyen kaynak reddedilir | Reddedildi | PASS |
| PERM_03 | Admin fonksiyon iznini kaldırır, kullanıcı çalıştıramaz, geri verince çalışır | Doğru | PASS |
| PERM_04 / PERM_05 | Açık ret ve tablo reddi; kullanıcı bazlı kayıt yalnızca o kullanıcıyı etkiler | Doğru | PASS |
| PERM_06 (15 parametre), PERM_07 | Admin olmayan, bilinmeyen ve pasif aktör `AdminService` işlemlerine erişemez | 18/18 reddedildi | PASS |
| PERM_08 | Admin kendini pasif yapamaz, başkasını yapabilir | Doğru | PASS |
| PERM_09-PERM_12 | Sahte DynamoDB Excel'den tohumlanır; değişiklikler ve kilit durumu yeniden başlatmada kalıcı; float reddi boto3 gibi | Doğru | PASS |
| PERM_13 | Ana akışta kaldırma sonrası `forbidden`, geri verince çalışır | Doğru | PASS |
| PERM_14 / PERM_15 | Token'daki rol iddiası yükseltmez; bilinmeyen/pasif kullanıcı token'ı backend'de reddedilir | Doğru | PASS |
| T_AUTHZ_01-08 | Fonksiyon veya tablo izni kaldırılınca `forbidden` ve depoya dokunulmaz; kullanıcı bazlı ret rol iznini ezer; `userid` yalnızca `invocation_state`'ten | Doğru | PASS |

### A.4 Test alanı 4: Tool'lar (`test_tools_e2e.py`): 6 tool x 6 senaryo

Beklenen sonuçlar Excel'den bağımsız hesaplanır. Senaryo hücreleri tool başına:

| Senaryo | Test id | Kapsam | Durum |
| --- | --- | --- | --- |
| 1. Doğru parametre | T_OK_01-T_OK_08, T_KEY_01-06 | 4 anahtarlı tool için her gerçek Keyid ham Excel ile eşleşir; 2 anahtarsız tool tüm tabloyu döndürür (13 ve 9 satır); 6 tool x 4 rol çalışır; gecikme tam dakika | PASS |
| 2. Yanlış parametre | T_WRONG_01 (4), T_NF_02 | Bilinmeyen/kısmi/alt dize anahtar veri döndürmeden `not_found`. Anahtarsız 2 tool için geçerli değil (N/A) | PASS |
| 3. Eksik parametre | T_MISS_01 (16), T_AUTHZ_08 | 4 anahtarlı tool x 4 varyant: `missing_parameter`, depoya dokunulmaz. Anahtarsız 2 tool için N/A | PASS |
| 4. Kayıt bulunamadı | T_NF_01 (4), T_NF_02, T_LEAK_02 | Geçerli biçimli ama olmayan anahtar `not_found`, veri sızmaz. Anahtarsız 2 tool için N/A | PASS |
| 5. Birden fazla kayıt | T_MULTI_01-04, T_OK_05/06, T_SORT_01-02 | Çok sevkiyatlı malzeme, 10+ duraklı sefer, çok kayıtlı `mip`; durak sırası sayısal artan | PASS |
| 6. Yetkisiz erişim | T_AUTHZ_01 (6), T_AUTHZ_02 (6), T_AUTHZ_03-07 | 6 tool için fonksiyon ve tablo izni kaldırılınca `forbidden`; diğer tool'lar etkilenmez | PASS |
| Ek: hata ve sızıntı | T_ERR_01-03, T_LEAK_01-06 | Depo hatası `error` döner, ayrıntı sızmaz; JSON-serileştirilebilir; auth tablosu açılmaz; her tool yalnızca kendi tablosunu bir kez okur | PASS |

Tool x senaryo matrisi: 36 hücrenin 30'u uygulanır ve PASS. 6 hücre (anahtarsız `get_delayed_truck` ve `get_truck_tobearrived` için yanlış, eksik, bulunamadı) anlamsız olduğu için N/A.

### A.5 Test alanı 5: Doğal dil (mock model, `test_nl_mock.py`, `test_history.py`)

| Id | Beklenen | Gerçekleşen | Durum |
| --- | --- | --- | --- |
| NLM_01 (60 parametre) | 6 fonksiyon x (5 TR + 5 EN) tek tur soruda doğru tool ve parametre, veri döner | 60/60 | PASS |
| NLM_02 (24 parametre) | Eksik Keyid: tool çağrılmaz, açıklayıcı soru | 24/24 | PASS |
| NLM_03 (4 parametre) | Model anahtarsız çağırsa bile guard durdurur | 4/4 | PASS |
| NLM_04 (10 parametre) | Takip mesajı: yalnızca Keyid gelince geçmişle doğru tool çalışır | 10/10 | PASS |
| NLM_05 (3), NLM_06 (1) | Bulunamadı ve yetkisiz yanıtlarda uydurma veri yok (4 halüsinasyon vakası) | 4/4 | PASS |
| NLM_07 | Pipeline'da kullanıcı izolasyonu | Doğru | PASS |
| test_history.py (17 test) | Geçmiş en fazla 10 mesaj, 2000 karakter, yalnızca user/assistant, bozuk öğe düşer, istek başına yeni ajan, iki kullanıcı karışmaz | 17/17 | PASS |
| test_chat_history_payload.py (4) | İstemci geçmişi yüke ekler (kırpılmış), yoksa yük değişmez | 4/4 | PASS |

### A.6 Test alanı 6: Dashboard

| Id | Beklenen | Gerçekleşen | Durum |
| --- | --- | --- | --- |
| DS11, UI_13 (2), UI_14 | KPI ve donut değerleri Excel `summary_df` ile aynı | Aynı | PASS |
| UI_09 (2), UI_10 (2) | Oturum başına yalnızca ilk görünümde otomatik, sonra kenar çubuğuyla; yeni girişte tekrar otomatik | Doğru | PASS |
| UI_11 (2), UI_12 | SUPPLIER ve ADMIN için otomatik Dashboard yok; ADMIN Admin Panel'e düşer | Doğru | PASS |
| UI_15 | `summary_df` tablo izni yoksa Dashboard gösterilmez | Doğru | PASS |

### A.7 Test alanı 7: Arayüz (Streamlit `AppTest`)

| Id | Beklenen | Gerçekleşen | Durum |
| --- | --- | --- | --- |
| UI_01 | Giriş ekranı: başlık, 3 öğe, maskeli şifre | Doğru | PASS |
| UI_02 (4 rol) | Başlıkta kullanıcı adı ve rol | 4/4 | PASS |
| UI_06 | Oturum yoksa veya rol bilinmiyorsa içerik gösterilmez | Doğru | PASS |
| UI_07 | Sohbet mesajı user ve assistant olarak saklanır ve görünür | Doğru | PASS |
| UI_08 | "Yeni sohbet" geçmişi ve çalışma zamanı oturum kimliğini sıfırlar, çıkış yapmaz | Doğru | PASS |
| UI_16 (3), UI_17, UI_18 | Admin dışı panele erişemez; Admin kullanıcı tablosunda şifre/özet yok; izin kaldır/ver etkisi görünür | Doğru | PASS |
| test_session_and_client.py (9 test) | Oturum, boşta zaman aşımı, istemci yük ve akış, `unauthenticated` olayı, 5xx durumu, Cognito gerekmez, router rol bileşimi | 9/9 | PASS |
| test_local_mode.py (10 test) | Yerel taşıma aynı JSON gövdesini gönderir ve SSE'yi ayrıştırır; loopback dışı URL reddedilir; yerel modda ARN gerekmez | 10/10 | PASS |

### A.8 Yükleme ve yerel araç testleri (`scripts/tests`)

| Id | Beklenen | Gerçekleşen | Durum |
| --- | --- | --- | --- |
| test_loader.py (5) | Dry-run yazmaz; apply idempotent; Decimal/NaN; q2 uyuşmazlığı raporlanır; gerçek dosya dry-run | 5/5 | PASS |
| test_seed.py (2) | Dry-run hiçbir şeye dokunmaz; apply idempotent, şifre özetli | 2/2 | PASS |
| test_local_tables.py (12) | `create_local_tables.py` yalnızca localhost/127.0.0.1 uç noktasında çalışır; AWS, `127.0.0.1.evil.com`, `user@127.0.0.1`, boş değer reddedilir; şema (GSI) doğru | 12/12 | PASS |

---

## B) Yerel entegrasyon (moto DynamoDB + gerçek Bedrock, `agentcore dev`)

Kod yolu üretimle aynıdır: `DynamoUserRepository`, `DynamoPermissionRepository`, `DynamoDataRepository`, `UserAuthService`, `AdminService` ve `AgentCoreClient`. Tek fark, `AWS_ENDPOINT_URL_DYNAMODB` ile DynamoDB'nin moto'ya, `LOGISTIC_AI_LOCAL_AGENT_URL` ile istemci taşımasının yerel `agentcore dev` sunucusuna yönlendirilmesidir. Bedrock çağrısı gerçektir, hiçbir AWS kaynağı oluşturulmadı. Betik: `scripts/local/e2e_local_flow.py`.

| Id | Beklenen | Gerçekleşen | Durum |
| --- | --- | --- | --- |
| LOC-01 | `create_local_tables.py`, uç nokta tanımsız, gerçek AWS URL'si veya `127.0.0.1.evil.com` iken çıkış kodu 2 ve tablo yok | 3/3 reddedildi | PASS |
| LOC-02 | moto'da 3 tablo (kb + `sheet-index`, users + `userid-index`, permissions) oluşur | 3 tablo oluştu | PASS |
| LOC-03 | `ingest --seed` dry-run: yazma yok | q1 46, q2 122, q3 199, q4 13, q5 9, summary_df 5, critical 131; role_user 166, permissions 52 | PASS |
| LOC-04 | `ingest --seed --apply` moto'ya yazar, şifreler özetlenir | Aynı sayılar yüklendi, atlanan 0 | PASS |
| LOC-05 | `agentcore dev --port 8082` model ve ortamla açılır | Açıldı (8081 başka projede meşgul, dokunulmadı) | PASS |
| LOC-06 | `UserAuthService` ile TRANSPORT_OFFICE girişi | Rol TRANSPORT_OFFICE | PASS |
| LOC-07 | `UserAuthService` ile ADMIN girişi | Rol ADMIN | PASS |
| LOC-08 | "Hangi tırlar geç kaldı?" gerçek model ve moto verisiyle yanıtlanır | 13 gecikmeli sefer tablo olarak döndü (örn. ilk satır 150 dk gecikme) | PASS |
| LOC-09 | ADMIN `AdminService.remove_permission` ile `get_delayed_truck` iznini rolden kaldırır; 32 sn sonra aynı soru | Yanıt: "Bu işlem için yetkiniz yok." (`forbidden`) | PASS |
| LOC-10 | ADMIN `set_permission` ile izni geri verir; 32 sn sonra aynı soru | Gecikmeli seferler yeniden listelendi | PASS |
| LOC-11 | `streamlit run app.py --server.port 8501 --server.headless true` açılır | `/_stcore/health` HTTP 200; yerel modda `AppTest` ile giriş ekranı hatasız çizildi (2 giriş alanı, hata yok) | PASS |
| LOC-12 | Yalnızca başlatılan süreçler durdurulur | moto, `agentcore dev` (8082) ve Streamlit (8501) durduruldu; 8080 ve 8081'deki süreçlere dokunulmadı | PASS |

Gözlemler:
- İzin değişikliği backend'e en fazla 30 sn gecikmeyle yansır (`PermissionService` önbelleği). Betik bu yüzden 32 sn bekler. Admin Panel ile backend ayrı süreç olduğundan bu bir tasarım sonucudur, hata değildir.
- Yerel gizli anahtar kısa olduğunda PyJWT `InsecureKeyLengthWarning` verir (bkz. F).

---

## C) Gerçek AWS entegrasyon testleri

| Id | Beklenen | Gerçekleşen | Durum |
| --- | --- | --- | --- |
| AWS-01 | Gerçek DynamoDB tabloları (`logistic-ai-kb`, `-users`, `-permissions`) ve `ingest --apply` | Tablo oluşturulmadı, yazılmadı. Neden: kullanıcının onayı olmadan gerçek kaynak oluşturulmaz | NOT TESTED |
| AWS-02 | AgentCore Runtime dağıtımı (`agentcore deploy`) ve çalışma zamanı ARN'i | Dağıtılmadı. Neden: onay yok ve Açık Karar 1 (yetkilendirici `AWS_IAM`) uygulanmadı | NOT TESTED |
| AWS-03 | Secrets Manager'dan `LOGISTIC_AI_SESSION_SECRET_ID` ile imza anahtarı okuma | Sır oluşturulmadı. Yalnızca birim düzeyinde sahte istemciyle seçim mantığı test edildi (A.0 içinde) | NOT TESTED |
| AWS-04 | `invoke_agent_runtime` SigV4 imzalı çağrı (`Boto3Transport`) | Gerçek çalışma zamanı yok. Taşıma birim testlerinde sahte istemciyle doğrulandı | NOT TESTED |
| AWS-05 | `additionalPolicies` ile IAM izinlerinin (`app/agent/policies/*.json`) dağıtımda uygulanması | Dağıtılmadı | NOT TESTED |
| AWS-06 | Dağıtılmış ortamda CloudWatch izleri ve Transaction Search | Dağıtılmadı | NOT TESTED |

---

## D) Gerçek LLM testleri (Bedrock Haiku 4.5)

Kaynak: `app/agent/tests/e2e/llm_results.json`. Testler `@pytest.mark.llm` ile işaretlidir ve yalnızca model çağırır (AWS kaynağı oluşturmaz). Model `global.anthropic.claude-haiku-4-5-20251001-v1:0`, `temperature=0.1`, `max_tokens=4096`, toplam 224 Bedrock çağrısı, 98 vaka. Bu bölümdeki sonuçlar önceki çalıştırmalardan alınmıştır, bu oturumda LLM testleri yeniden çalıştırılmadı (maliyet).

| Id | Beklenen | Gerçekleşen | Durum |
| --- | --- | --- | --- |
| LLM_01 tool seçimi (60 tek tur) | Doğru tool ve parametre | tool_selection 60/60 = %100, arg_accuracy %100 | PASS |
| LLM_02 eksik Keyid (24) | Tool çağırmadan Keyid ister | missing_key_clarification 24/24 = %100 | PASS |
| LLM_03 takip (10) | Önceki bağlamla doğru tool | followup_success 10/10 = %100 | PASS |
| LLM_04 bulunamadı (3) | Kayıt uydurmaz | 3/3 | PASS |
| LLM_05 yetkisiz (1) | `forbidden`, veri sızdırmaz | 1/1 | PASS |
| LLM_99 doğruluk eşikleri | Tüm metrikler eşiğin üstünde; hallucination_free %100 | Eşikler geçildi | PASS |

İstem düzeltmesi öncesi ve sonrası:

| Metrik | Öncesi | Sonrası |
| --- | --- | --- |
| Eksik Keyid'de açıklama isteme (24 vaka) | %45,8 | %100 (24/24) |
| Diğer metrikler (tool seçimi, parametre, takip, halüsinasyon) | Öncesi değerler dosyada kayıtlı değil | %100 |

`max_tokens` sorunu: uzun tablo yanıtlarında (ör. tüm gecikmeli seferler) küçük bir `max_tokens` sınırı yanıtı kesiyordu (`MaxTokensReachedException`). Varsayılan 4096'ya çıkarıldı, `LOGISTIC_AI_MAX_TOKENS` ile ayarlanabilir ve sınır yine de aşılırsa kullanıcıya teknik ayrıntı içermeyen Türkçe bir ileti (`response_too_long`) döner. Birim testleri: `test_max_tokens.py` (3 test, PASS).

---

## E) Düzeltilen hatalar ve üretim değişiklikleri

| # | Konu | Değişiklik | Doğrulayan test | Durum |
| --- | --- | --- | --- | --- |
| 1 | Konuşma geçmişi desteği | İstemci her çağrıda mevcut oturumun geçmişini yüke ekler (en fazla 10 mesaj, 2000 karakter). Backend geçmişi doğrular ve yalnızca o istek için kullanır | `test_history.py`, `test_chat_history_payload.py`, NLM_04, LLM_03 | PASS |
| 2 | İstek başına yeni ajan | Ajan durumu kullanıcılar arasında karışmasın diye her istekte yeni `Agent` kurulur, yalnızca model istemcisi önbelleklenir | `test_agent_is_fresh_per_request...`, NLM_07 | PASS |
| 3 | Router: ilk görünümde Dashboard | MATERIAL_RESPONSIBLE ve TRANSPORT_OFFICE için yalnızca oturumdaki ilk görünümde otomatik, sonra gezinmeyle | UI_09, UI_10, UI_11 | PASS |
| 4 | "Yeni sohbet" düğmesi | Geçmişi ve çalışma zamanı oturum kimliğini sıfırlar, çıkış yapmaz | UI_08 | PASS |
| 5 | Admin kenar çubuğu başlığı | Admin Panel için kenar çubuğu başlığı/yönlendirmesi düzeltildi | UI_12, UI_16-UI_18 | PASS |
| 6 | `max_tokens` ve `response_too_long` | Bkz. D bölümü | `test_max_tokens.py` | PASS |
| 7 | `log_lockout` | Hesap kilitleme olayı denetim kaydına yazılır (`app/agent/logistic_ai_shared_auth/common/audit.py`) | AUTH_08, AUTH_09, PERM_11 | PASS |
| 8 | Gecikme sistem saatine bağlı değil | Gecikme yalnızca veriden okunur, `datetime.now` kullanılmaz | DS08-DS10 | PASS |
| 9 | Yerel çalıştırma yolu (bu görev) | `LocalHttpTransport` (`LOGISTIC_AI_LOCAL_AGENT_URL`, yalnızca loopback), yerel modda `agent_runtime_arn` zorunlu değil, `scripts/local/` altında moto tabloları, `env.example`, uçtan uca betik | `test_local_mode.py`, `test_local_tables.py`, LOC-01-LOC-12 | PASS |

Yuvarlama notu: araçlar gecikmeyi tam dakikaya yuvarlar (T_OK_08). Örneğin 57,617 dakika "58 dk" olarak gösterilir. `critical.Gecikme_Suresi` ise Excel'de metin olarak kesilmiş ("57 dk") durumdadır. İki alan farklı kaynaktan geldiği için aynı sevkiyatta 58 ve 57 görülebilir. Bu bir hata değildir, README'deki ondalık gösterim bulgusuyla ilgilidir. Karar gerekir: tek bir yuvarlama kuralı.

Bu görevdeki çalıştırmalarda başarısız test olmadı, bu yüzden "önce/sonra" düzeltmesi gerekmedi. Betiğin ilk çalıştırması paralel araç çağrısındaki zamanlama nedeniyle dosyayı bulamadı (ürün hatası değil), dosya yazıldıktan sonra tekrar çalıştırıldı ve geçti.

---

## F) Bilinen açıklar ve riskler

| # | Risk | Etki | Öneri |
| --- | --- | --- | --- |
| 1 | **Açık Karar 1:** `agentcore/agentcore.json` hâlâ Cognito `CUSTOM_JWT` yetkilendiricisini kullanıyor | Dağıtılmış ortamda SigV4 + Session_Token akışı çalışmaz | Onayla ve `AWS_IAM` yap, sonra dağıt |
| 2 | Admin Panel izin tablosu aynı çalıştırmada bayat kalabilir | Bir değişiklikten sonra panel tablosu yenilenmezse eski durum görünür. Backend etkisi en fazla 30 sn gecikir (önbellek) | Değişiklik sonrası listeyi yeniden oku, önbellek süresini belgeleyin |
| 3 | `summary_df` ile `question1` tutarsız | `summary_df` 18 tamamlanan sefer bildirir, `question1` 46 seferin hepsini aktif gösterir | Veri sahibiyle doğrulayın. Dashboard `summary_df`'e güvenir |
| 4 | 114 kritik malzeme `question2`'de yok | `get_material_truck_allocation` bu malzemeler için "kayıt bulunamadı" döner | Veri uyuşmazlığı, hata değil. Kaynak sistemde kontrol edin |
| 5 | Excel'de düz metin şifreler | `role_user` sheet'i tüm şifreleri açık içerir ve çoğu zayıf (6 hane) | Excel'i sürüm kontrolü dışında tutun, yüklemeden sonra silin, şifreleri sıfırlatın |
| 6 | Sohbette bir kişisel erişim belirteci (PAT) paylaşıldı | Sızmış sayılmalı | **PAT'ı hemen iptal edin (revoke)** ve yenisini oluşturun |
| 7 | Yerel gizli anahtar 32 bayttan kısa olabilir (PyJWT `InsecureKeyLengthWarning`) | Zayıf HS256 anahtarı. Kod en az 16 karaktere izin veriyor | Üretimde Secrets Manager'da en az 32 bayt rastgele değer kullanın, alt sınırı 32'ye çıkarmayı değerlendirin |
| 8 | Gecikme yuvarlaması 57,617 → 58 ile "57 dk" metni | Aynı veri için iki farklı gösterim | Tek yuvarlama kuralı belirleyin |
| 9 | Gerçek AWS entegrasyonu test edilmedi (bkz. C) | Dağıtım davranışı kanıtsız | Onaydan sonra C bölümü testlerini çalıştırın |
| 10 | Satır bazlı veri kısıtlaması yok (kapsam dışı) | İzinli her rol tüm satırları görür | Gelecek faz |
