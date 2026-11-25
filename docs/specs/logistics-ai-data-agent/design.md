# Design Document

## Overview

Bu tasarım, `logistics-ai-data-agent` özelliğini (Faz 2) mevcut `Logistic_AI` projesinin üzerine ekler. Mevcut Strands Agents + Amazon Bedrock AgentCore Runtime yapısı (runtime `agent`, `BedrockAgentCoreApp`, `agentcore deploy`) ve Faz 1 modülleri korunur. Faz 1'deki Cognito tabanlı kimlik doğrulama, `role_user` + DynamoDB tabanlı kimlik doğrulama ile değiştirilir (Açık Karar 1).

### Hedefler

- Excel verisini sheet/kolon adlarını koruyarak kesin eşleşmeli bir Data_Store'a yüklemek.
- `role_user` kayıtlarını argon2id özetleriyle DynamoDB User_Store'a aktarmak.
- Rol ve kullanıcı bazlı izinleri DynamoDB'de tutmak; her Tool çağrısından önce backend'de kontrol etmek.
- ADMIN rolü ve Admin Panel ile izin/kullanıcı yönetimi.
- Altı Strands `@tool` fonksiyonu, Türkçe/İngilizce sistem istemi.
- `summary_df` tabanlı, role göre otomatik görünen Dashboard.

### Kapsam Dışı

- Bedrock Knowledge Base (vektör arama), Memory, MCP, Skills.
- Satır bazlı veri filtreleme (ör. tedarikçinin yalnızca kendi seferlerini görmesi). Bkz. Açık Karar 4.
- AWS dağıtımı. Kullanıcı onayı olmadan yapılmaz.

## Açık Kararlar (Kullanıcı Onayı Gerekir)

1. **AgentCore gelen kimlik doğrulaması.** Mevcut `agentcore.json` Cognito `CUSTOM_JWT` yetkilendiricisi kullanıyor. `role_user` tabanlı girişte Cognito token'ı oluşmaz.
   - **Seçenek A (önerilen):** Yetkilendirici `AWS_IAM` (SigV4) olur. Streamlit_Client `bedrock-agentcore` `invoke_agent_runtime` ile çağırır ve payload'a imzalı Session_Token ekler. Backend token'ı doğrular ve kullanıcının rol/izin/aktiflik bilgisini DynamoDB'den kendisi okur. Deployment konfigürasyonunda tek değişiklik yetkilendirici türüdür.
   - **Seçenek B:** Yetkilendirici Cognito olarak kalır; kullanıcılar Cognito'ya aktarılır. Cognito en az 6 karakterlik şifre ister. Excel'de 5 haneli bir şifre var (veri kalitesi bulgusu 5); o kullanıcı için şifre sıfırlama gerekir. Ayrıca kullanıcı durumu iki yerde (Cognito + DynamoDB) tutulur.
   - Karar verilmeden `agentcore.json` değiştirilmez. Kod, taşıma katmanından bağımsız yazılır (`IdentityResolver` arayüzü).
2. **Veri deposu.** "Knowledge Base" için Bedrock KB yerine DynamoDB kullanılır, çünkü kesin eşleşme zorunludur. Tablolar Excel'den yüklenir. Excel günlük yenilenecekse yükleme betiği yinelenebilir olmalıdır (yapıldı) ve S3/zamanlanmış yükleme sonraki aşamadır.
3. **Session_Token imzalama.** HS256, anahtar AWS Secrets Manager'dan okunur. Yerel geliştirmede ortam değişkeni kullanılır.
4. **Veri kapsamı.** `role_user` içinde SUPPLIER kullanıcılarının `USERID` değerleri tedarikçi kodu gibi görünüyor, ancak istek bunu kısıtlama olarak tanımlamıyor. Bu fazda tüm roller (izin verilen) tablolardaki tüm satırları görür. Satır bazlı kısıtlama istenirse ayrı bir spec olur.
5. **ADMIN ve operasyonel tablolar.** Excel `permissions` sheet'i ADMIN'e de tüm tablolar için izin veriyor. Tohumlamada ADMIN'e operasyonel tablo ve fonksiyon izni verilir (Admin yönetim işlemleri ayrı `ADMIN_*` kaynaklarıyla korunur). Siz yalnızca yönetim yetkisi istiyorsanız tohumdan çıkarılır.

## Architecture

### Dağıtım Topolojisi

```
Streamlit_Client (yerel/konteyner)                AgentCore Runtime `agent` (CodeZip)
 ├─ ui: login, chat, dashboard, admin_panel        ├─ main.py (entrypoint, lazy)
 ├─ auth: AuthService (DynamoDB users)             ├─ identity: Session_Token doğrulama
 ├─ session: SessionManager                        ├─ agent: Strands Agent + system prompt
 ├─ dashboard: summary_df okuma                    ├─ tools: 6 adet @tool
 └─ admin: AdminService                            └─ authorization: PermissionService
        │  SigV4 + Session_Token (payload)                   │
        └────────────────────────────────────────────────────┘
                         DynamoDB: users, permissions, kb
```

Streamlit_Client AgentCore üzerinde çalışmaz. Dashboard ve Admin_Panel Streamlit_Client içinde, ortak `logistic_ai_shared_auth` ve yeni `logistic_ai_data` paketlerini kullanarak DynamoDB'ye doğrudan erişir. Her ikisi de aynı `PermissionService` ve `AdminService` kodunu çağırır; yetki kontrolü UI'a değil servis katmanına bağlıdır.

### Katmanlar ve Modüller

| Katman | Paket / Dosya | Sorumluluk |
| --- | --- | --- |
| Authentication | `logistic_ai_shared_auth/auth/` | `PasswordHasher` (argon2id), `UserAuthService`, `SessionTokenService`, kilitleme |
| Authorization | `logistic_ai_shared_auth/authorization/` | `PermissionService`, `AdminService`, rol sabitleri |
| Data Access | `logistic_ai_data/` | `DataRepository` arayüzü, `DynamoDataRepository`, `InMemoryDataRepository`, `key_normalizer` |
| Ingestion | `Logistic_AI/scripts/ingest/` | Excel okuma, güvenli JSON parse, yükleme, rapor |
| Tools | `app/agent/tools/` | 6 `@tool`, ortak `guard` dekoratörü |
| Agent | `app/agent/agent_factory.py`, `prompts/system_prompt.py`, `model/load.py` | Strands Agent, sistem istemi, model |
| UI | `streamlit_client/logistic_ai/ui/` | login, chat, dashboard, admin_panel, router |

Kural: Tools ve UI yalnızca servis arayüzlerini çağırır; DynamoDB istemcisine doğrudan dokunmaz.

### Proje Yapısı (yeni/değişen)

```
Logistic_AI/
├── Data/Agent_AWS_2026-11-24.xlsx        # sürüme eklenmez
├── scripts/ingest/{excel_reader,json_safe,loader,seed,report}.py, run_ingest.py
├── app/agent/
│   ├── main.py                           # değişir: yeni kimlik çözümleme
│   ├── agent_factory.py                  # yeni
│   ├── prompts/system_prompt.py          # değişir
│   ├── model/load.py                     # değişir
│   ├── tools/{__init__,guard,logistics_tools}.py   # yeni
│   ├── logistic_ai_data/                 # yeni
│   └── logistic_ai_shared_auth/{auth,authorization}/   # genişler
└── streamlit_client/logistic_ai/ui/{dashboard,admin_panel,login_screen,home_screen,router}.py
```

Faz 1'in `auth/cognito_service.py` ve `TokenVerifier` kodu silinmez; Karar 1 sonuçlanana kadar kullanılmaz ve çözümlenince kaldırılır.

## Components and Interfaces

### Anahtar normalizasyonu

```python
def normalize_key(value: object) -> str:
    """Yalnızca strip + upper. Sıfır ve sondaki harf korunur. float ise '.0' eklemez."""
```

Excel okurken `openpyxl` ile hücre ham değeri alınır; anahtar kolonlar (`shipment_id`, `materialno`, `supplier_code`, `mip`, `USERID`) `str()` ile saklanır. Tamsayı gelen `supplier_code` ve `mip` değerleri `str(int)` olur; float ise tamsayıya eşitse `int` üzerinden çevrilir.

### Güvenli JSON

```python
def safe_json_loads(raw: object) -> tuple[dict | list | None, str | None]:
    """Hata durumunda (None, hata_türü) döner; istisna fırlatmaz."""
```

### DataRepository

```python
class DataRepository(Protocol):
    def get_by_key(self, table: str, key: str) -> list[dict]: ...   # kesin eşleşme
    def get_all(self, table: str) -> list[dict]: ...
```

`question3` sonuçları `stop_sequence` sayısal artan; DynamoDB sıralama anahtarı sıfır dolgulu (`0001`) olduğu için sıralama doğaldır, ayrıca `sorted(..., key=int)` ile garanti edilir.

### Kimlik doğrulama

```python
class UserAuthService:
    def authenticate(self, username: str, password: str) -> SessionToken: ...   # AuthError
    def logout(self, ctx) -> None: ...

class SessionTokenService:
    def issue(self, userid: str, username: str, role: str) -> str: ...
    def verify(self, token: str) -> VerifiedSession: ...   # userid, username, role, exp
```

Token yalnızca `uid`, `usr`, `role`, `iat`, `exp` içerir. **Backend rolü token'dan değil User_Store'dan okur** (token yalnızca kimliği taşır); token'daki rol UI gösterimi içindir ve karar için kullanılmaz.

### Permission

```python
class PermissionService:
    def check(self, userid: str, resource_type: str, resource: str) -> Decision
    def require_tool(self, userid: str, function: str, tables: Sequence[str]) -> None   # PermissionDenied
```

Karar sırası: (1) kullanıcı kaydı yok veya pasif → ret; (2) kaynak `role_user`/`permissions` ise → ret; (3) kullanıcı bazlı kayıt; (4) rol bazlı kayıt; (5) ret. Sonuçlar 30 sn TTL ile bellekte önbelleklenir (gereksinim 3.7: en fazla 60 sn). Yönetim işlemi sonrası aynı süreçteki önbellek temizlenir.

### Tool koruması

```python
def guarded(function_name: str, tables: Sequence[str], key_param: str | None):
    """Doğrulanmış çağrı bağlamından kimliği alır, izin kontrolü yapar, Key_ID'yi doğrular."""
```

Strands `@tool(context=True)` ile `ToolContext.invocation_state` içinden `userid` okunur. `invocation_state`, `main.py` tarafından Session_Token doğrulandıktan sonra doldurulur; LLM bu alanı göremez veya değiştiremez. (Uygulama sırasında kullanılan Strands sürümünün `ToolContext` API'si Strands MCP dokümanıyla doğrulanır.)

Tool yanıt şeması (tümü JSON uyumlu dict):

```python
{"status": "ok", "rows": [...], "count": n}
{"status": "missing_parameter", "parameter": "shipment_id", "message": "..."}
{"status": "not_found", "key": "...", "message": "Kayıt bulunamadı"}
{"status": "forbidden", "message": "Bu işlem için yetkiniz yok"}
{"status": "error", "message": "Veri okunamadı"}
```

Fonksiyon → kaynak eşlemesi: `get_truck_location→question1`, `get_material_truck_allocation→question2`, `get_truck_route_info→question3`, `get_delayed_truck→question4`, `get_truck_tobearrived→question5`, `get_critical_part_status→critical`.

Tool çıktıları: JSON kolonları (`question1`, `question2`, `question4`, `question5`) parse edilerek yapılandırılmış alanlara açılır; parse edilemeyen satırlar yükleme sırasında zaten atlanmıştır. `question2` JSON'u malzeme bazında yinelendiği için çıktı Excel kolonlarından (`shipment_id`, `quantity`, `tofas_etadate`) üretilir; JSON ile kolon tutarlılığı yükleme sırasında doğrulanır.

### Admin_Service

```python
class AdminService:
    def set_user_active(self, actor, target_userid, active: bool)
    def set_permission(self, actor, subject_type: "USER"|"ROLE", subject, resource_type, resource, allowed: bool)
    def remove_permission(self, actor, subject_type, subject, resource_type, resource)
    def list_users(self, actor) -> list[UserView]       # şifre özeti yok
    def list_permissions(self, actor, subject_type, subject)
```

Her metot ilk adımda `actor`'ı User_Store'dan okuyup aktif ADMIN olduğunu doğrular. Kaynak adı yalnızca bilinen `TABLE`/`FUNCTION` listesinden olabilir; `role_user`/`permissions` reddedilir.

### Dashboard

```python
def load_kpis(repo: DataRepository) -> Kpis   # total, delayed, completed, in_progress, delay_rate
```

`summary_df` satırları `Durum` adına göre okunur. `delay_rate = delayed / total * 100` hesaplanır, `total == 0` ise 0. Kaynaktaki `Gecikme Oranı` (kesir) ile fark `> 0.0005` ise uyarı günlüğü yazılır. Donut: Streamlit `st.plotly_chart` (plotly, `hole=0.55`) kullanılır; Tamamlanan ve Devam Eden dilimleri.

Görünürlük: `role in {TRANSPORT_OFFICE, MATERIAL_RESPONSIBLE}` ve `summary_df` tablo izni. SUPPLIER ve ADMIN için otomatik gösterilmez (ADMIN, Admin Panel'e yönlenir).

### Agent

`agent_factory.build_agent()` lazy çağrılır; `Agent(model=load_model(), system_prompt=SYSTEM_PROMPT, tools=[...6 tool])`. Placeholder ajanı Faz 1'den kaldırılır. `main.py` her istekte: payload parse → Session_Token doğrula → kullanıcıyı User_Store'dan oku (pasifse reddet) → `invocation_state={"userid": ...}` ile ajanı akış olarak çalıştır.

## Data Models

### DynamoDB tabloları

| Tablo | Anahtar | Alanlar |
| --- | --- | --- |
| `logistic-ai-users` | PK `USERNAME` (S); GSI `userid-index` PK `USERID` | `USERID`(S), `ROLE`(S), `password_hash`, `active`(BOOL), `failed_count`, `locked_until`, `created_at` |
| `logistic-ai-permissions` | PK `SUBJECT` (`ROLE#SUPPLIER` / `USER#129-01`), SK `RESOURCE` (`TABLE#question1` / `FUNCTION#get_truck_location`) | `allowed`(BOOL), `updated_by`, `updated_at` |
| `logistic-ai-kb` | PK `PK` (`question1#FA2002267103`, `question4#ALL`), SK `SK` (`0001` veya satır sırası); GSI `sheet-index` PK `sheet` | `sheet`, `data`(map; Excel kolon adlarıyla), `load_id` |

`logistic-ai-kb` yüklemesi: aynı `load_id` ile PutItem; yükleme başında ilgili sheet `sheet-index` ile silinir ve yeniden yazılır (idempotent). Key_ID alanları her yerde string tutulur.

### Anahtar eşlemesi

| Sheet | PK değeri | SK |
| --- | --- | --- |
| question1 | `question1#<shipment_id>` | `0000` |
| question2 | `question2#<materialno>` | `<shipment_id>` |
| question3 | `question3#<shipment_id>` | `<stop_sequence 4 hane>` |
| question4, question5, summary_df | `<sheet>#ALL` | satır sırası |
| critical | `critical#<mip>` | `<shipment_id>#<materialno>` |

### Tohum (seed) izinleri

Excel `permissions` sheet'i okunur: 4 rol × (7 tablo + 6 fonksiyon). Hata varsa (bilinmeyen kaynak, `ALLOWED` ∉ {0,1}) kayıt atlanır ve raporlanır. Yinelenen yükleme mevcut kayıtları ezmez (`attribute_not_exists` koşulu), böylece admin değişiklikleri korunur.

## Veri Kalitesi Bulguları (Excel analizi)

1. **Düz metin şifreler.** `role_user` 166 kullanıcı için şifreyi düz metin içeriyor; ADMIN şifresi de dahil. Şifreler tekrar eden değil, ancak 158'i 6 haneli sayı (zayıf). Excel sürüme eklenmez (`.gitignore`); aynı dosyanın ikinci kopyası `.kiro/Logistic_AI/Data/` altında duruyor ve silinmeli veya `.gitignore` kapsamına alınmalı.
2. **Şifre türü karışık.** 165 şifre sayı (int), 1'i metin. Sayıya çevrildiği için baştaki sıfırlar kaybolmuş olabilir; 5 haneli şifre bu şüpheyi taşıyor. Şifreler `str(int)` ile okunur; 5 haneli şifre doğrulanmalı.
3. **USERID türü karışık.** 163 sayı, 3 metin (`129-01`, `129-00`, `ADMIN001`). Hepsi string saklanır.
4. **Tablolar arası anahtar türü tutarsızlığı.** `supplier_code` `question2`'de sayı, `critical`'da metin. `mip` her iki yerde sayı. Hepsi string olarak normalize edilir.
5. **Sayısal olarak kaydedilen ondalıklar.** `question4.delay_time` karışık int/float (`76.18333`), `critical.Gecikme_Suresi` ise aynı değeri `76 dk` metni olarak kesiyor. JSON içindeki `mikta` ve `eta_diff_min` float (`54.0`, `4.0`) iken kolonlar int. Gösterimde tamsayıya yuvarlama kuralı gerekir.
6. **Excel formülü yok.** `summary_df` dahil hiçbir sheet formül içermiyor; tüm değerler sabit. `Gecikme Oranı` kesir (0.2826) olarak saklı, yüzde değil. "Formülleri doğru değerlendir" gereksinimi oran hesaplanarak karşılanır.
7. **`summary_df` ile `question1` uyuşmuyor.** `summary_df`: Tüm 46, Geciken 13, Tamamlanan 18, Devam Eden 28. `question1` 46 seferin hepsini aktif durumda gösteriyor (Yolda 26, Sefer başlamadı 16, Boşkasada 2, Yüklemede 2); tamamlanmış sefer yok. "Tamamlanan" değeri başka kaynaktan türetilmiş. Dashboard yalnızca `summary_df`'e güvenir; tutarsızlık raporlanır.
8. **`critical` ile `question2` kesişmiyor.** `critical` içindeki 114 malzeme numarası `question2`'de yok. Kullanıcı `critical`'daki bir malzemeyi `get_material_truck_allocation` ile sorarsa "kayıt bulunamadı" alır; bu veri uyuşmazlığıdır, hata değildir.
9. **Sefer kapsamı farkı.** `critical` yalnızca 12 sefer ve 5 farklı `mip` (18, 19, 25, 47, 73) içeriyor; `question4`'ün 13 geciken seferinin tamamı `question1`'de var, ancak `critical` 12'sini kapsıyor.
10. **Yer tutucu telefon.** `question5.driver_phone` değerleri `phone1…phone9`; gerçek numara yok. `driver_name` içinde çift boşluk var (`NİHAT  AKINCI`).
11. **`question3` yalnızca son durak için `location_text` ve `laststop_explanation` dolduruyor.** Her seferde tam 1 satır dolu; diğer 153 satır boş (NULL). Boş değerler hata sayılmaz.
12. **Başlık yazım hataları.** `critical.KrtiklikZaman` (Kritiklik), `Functions.Keyiid_explanation`, JSON anahtarı `mikta` ve `Eta Zamanı`. İstek gereği adlar korunur.
13. **Tarih türleri.** `question3` ve `critical` tarihleri gerçek `datetime`; `question1/2/5` tarihleri metin. İkisi de `YYYY-MM-DD HH:MM:SS` metnine normalize edilir.
14. **JSON bütünlüğü iyi.** Tüm JSON kayıtları (46 + 122 + 13 + 9) geçerli; `question2` JSON'u kolonlarla tutarlı. Bozuk kayıt yok, ancak parse koruması yine de zorunludur.
15. **İsimlendirme.** `permissions` sheet'i istekte yok; yalnızca tohum için kullanılıyor.

## Correctness Properties

### Property 1: Anahtar normalizasyonu

Her string `s` için `normalize_key(s)` baştaki sıfırları ve içerik karakterlerini değiştirmez; `normalize_key(normalize_key(s)) == normalize_key(s)`.

**Validates: Requirements 1.3, 1.4, 1.9**

### Property 2: Kesin eşleşme

`get_by_key(t, k)` yalnızca `normalize_key(kayıt.anahtar) == normalize_key(k)` olan kayıtları döndürür.

**Validates: Requirements 1.8, 5.2, 5.3, 5.7**

### Property 3: Güvenli parse

Herhangi bir girdi için `safe_json_loads` istisna fırlatmaz.

**Validates: Requirements 1.5, 1.6**

### Property 4: Şifre özeti

Özetlenmiş değer açık şifreyi içermez; doğru şifre doğrulanır, farklı şifre doğrulanmaz.

**Validates: Requirements 2.2, 2.3**

### Property 5: Deny-by-default

Kaydı olmayan (kullanıcı, kaynak) çiftleri için `check` ret döner; pasif kullanıcı için her kaynak reddedilir.

**Validates: Requirements 3.5, 3.8**

### Property 6: Öncelik

Kullanıcı bazlı kayıt, rol bazlı kaydı geçersiz kılar.

**Validates: Requirements 3.4**

### Property 7: Auth_Table kapalı

`role_user` ve `permissions` için hiçbir izin kaydı ile `check` izin vermez.

**Validates: Requirements 3.3**

### Property 8: Tool koruması

İzin yokken Tool depoya hiç erişmez; çıktı `forbidden` olur.

**Validates: Requirements 5.10, 5.11**

### Property 9: Key_ID zorunlu

Boş/boşluk Key_ID için depo çağrılmaz ve `missing_parameter` döner.

**Validates: Requirements 5.8**

### Property 10: Sıralama

`get_truck_route_info` çıktısında `stop_sequence` sayısal artandır.

**Validates: Requirements 5.4**

### Property 11: Dashboard oranı

`delay_rate = delayed/total*100`, `total=0` için 0; `completed + in_progress == total` değilse uyarı kaydı vardır.

**Validates: Requirements 7.5, 7.7, 7.8**

### Property 12: Admin öz koruma

Admin kendini veya son aktif ADMIN'i pasif yapamaz; ADMIN olmayan hiçbir çağıran yönetim işlemi yapamaz.

**Validates: Requirements 4.9, 4.10**

### Property 13: Sızıntı yok

Günlük çıktıları şifre, özet ve token içermez.

**Validates: Requirements 2.3, 9.3**

### Property 14: İdempotent yükleme

Aynı Excel iki kez yüklenince kayıt sayıları aynı kalır ve admin değişiklikleri ezilmez.

**Validates: Requirements 1.10, 3.2**


## Error Handling

- Depo/izin hataları Tool içinde yakalanır, `{"status":"error"}` döner; ayrıntı yalnızca günlüğe yazılır (`safe_error_message`).
- Giriş hataları tek genel mesajla döner; kilitli ve pasif hesap için ayrı mesaj yoktur.
- Dashboard hatasında genel mesaj gösterilir, uygulama çökmez.

## Testing Strategy

pytest + Hypothesis. `InMemoryDataRepository`, bellek içi User/Permission store ve sabit `Clock` ile gerçek AWS olmadan. Özellik testleri P1–P14 için yazılır, DynamoDB uyarlayıcıları `botocore.stub.Stubber` ile test edilir. Excel'e karşı entegrasyon testi gerçek dosyayı okur (dosya yoksa atlanır).
