# Logistics AI Assistant (Faz 2: Veri Ajanı, `role_user` Kimlik Doğrulaması ve Dinamik Yetkilendirme)

> **Dağıtım öncesi zorunlu adım (Açık Karar 1):** `agentcore/agentcore.json` hâlâ Faz 1'den kalan Cognito `CUSTOM_JWT` yetkilendiricisini kullanıyor. Faz 2 akışı dağıtılmış ortamda çalışmadan önce yetkilendirici tasarım gereği **`AWS_IAM` (SigV4)** olarak değiştirilmelidir. Bu değişiklik henüz yapılmadı. `agentcore deploy`, DynamoDB tablolarının oluşturulması ve veri yükleme (`--apply`) **kullanıcının açık onayı olmadan çalıştırılmaz**. Ayrıntılar için [Açık Karar 1 durumu](#açık-karar-1-durumu-agentcore-kimlik-doğrulaması) bölümüne bakın.

## Proje amacı

Bu proje, lojistik süreçleri için bir yapay zekâ veri ajanı kurar. Kullanıcılar Excel'den yüklenen `role_user` kayıtlarıyla giriş yapar (şifreler argon2id özetli saklanır). Rol ve izinler DynamoDB'den okunur. Amazon Bedrock AgentCore Runtime üzerinde çalışan Strands ajanı, altı `@tool` ile kesin eşleşmeli veri deposunu (DynamoDB `kb` tablosu) sorgular. Her Tool çağrısı, çağıran kullanıcının izinleri denetlendikten sonra çalışır.

Faz 2 kapsamı: Excel verisinin yüklenmesi, `role_user` tabanlı giriş, dinamik izin yönetimi (Admin Panel), altı Strands Tool'u, sistem istemi, rol bazlı Dashboard, denetim kaydı.

Faz 1'in Cognito tabanlı kodu (`cognito_service.py`, `TokenVerifier`) Açık Karar 1 sonuçlanana kadar silinmemiştir ve Faz 2 akışında kullanılmaz.

## Mimari ve dağıtım topolojisi

```
Streamlit_Client (yerel/konteyner)                AgentCore Runtime `agent` (CodeZip)
 ├─ ui: login, chat, dashboard, admin_panel        ├─ main.py (giriş noktası, tembel başlatma)
 ├─ auth: UserAuthService (DynamoDB users)         ├─ identity: Session_Token doğrulama
 ├─ session: SessionManager                        ├─ agent: Strands Agent + sistem istemi
 ├─ dashboard: summary_df okuma                    ├─ tools: 6 adet @tool
 └─ admin: AdminService                            └─ authorization: PermissionService
        │  SigV4 + Session_Token (payload)                   │
        └────────────────────────────────────────────────────┘
                         DynamoDB: users, permissions, kb
```

- **Streamlit_Client** AgentCore üzerinde çalışmaz. Giriş, sohbet, Dashboard ve Admin Panel burada çalışır. Dashboard ve Admin Panel, ortak `logistic_ai_shared_auth` ve `logistic_ai_data` paketleri üzerinden DynamoDB'ye doğrudan erişir. Yetki kontrolü UI'a değil servis katmanına (`PermissionService`, `AdminService`) bağlıdır.
- Sohbet isteği, `bedrock-agentcore` `invoke_agent_runtime` ile SigV4 imzalı gönderilir ve payload'a imzalı **Session_Token** (HS256, 30 dakika ömürlü; `uid`, `usr`, `role`, `iat`, `exp`) eklenir.
- **Agent_Backend** AgentCore Runtime'da `agent` adıyla çalışır. Her istekte Session_Token'ı doğrular, kullanıcıyı DynamoDB'den okur (pasifse reddeder) ve rolü token'dan değil kullanıcı kaydından alır. Kimlik, Tool'lara `invocation_state["userid"]` ile iletilir.
- Tool'lar yalnızca servis arayüzlerini çağırır; DynamoDB istemcisine doğrudan dokunmaz. `role_user` ve `permissions` kaynakları hiçbir Tool'a veya role açılmaz.
- Ayrıntılı tasarım: [docs/specs/logistics-ai-data-agent/design.md](docs/specs/logistics-ai-data-agent/design.md).

### DynamoDB tabloları

Tablolar bu repoda otomatik oluşturulmaz. Yükleme öncesinde kullanıcı onayıyla oluşturulmuş olmalıdır. Tablo adları aşağıdaki ortam değişkenlerinden okunur (varsayılan adlar parantez içindedir).

| Tablo | Anahtar | İndeks | Alanlar |
| --- | --- | --- | --- |
| `logistic-ai-users` | PK `USERNAME` (S) | GSI `userid-index`: PK `USERID` | `USERID` (S), `ROLE` (S), `password_hash`, `active` (BOOL), `failed_count`, `locked_until`, `created_at` |
| `logistic-ai-permissions` | PK `SUBJECT` (`ROLE#<rol>` veya `USER#<userid>`), SK `RESOURCE` (`TABLE#<ad>` veya `FUNCTION#<ad>`) | yok | `allowed` (BOOL), `updated_by`, `updated_at` |
| `logistic-ai-kb` | PK `PK`, SK `SK` | GSI `sheet-index`: PK `sheet` | `sheet`, `data` (map; Excel kolon adlarıyla), `load_id` |

`logistic-ai-kb` anahtar eşlemesi:

| Sheet | PK | SK |
| --- | --- | --- |
| `question1` | `question1#<shipment_id>` | `0000` |
| `question2` | `question2#<materialno>` | `<shipment_id>` |
| `question3` | `question3#<shipment_id>` | `<stop_sequence>` (4 hane, sıfır dolgulu) |
| `question4`, `question5`, `summary_df` | `<sheet>#ALL` | satır sırası |
| `critical` | `critical#<mip>` | `<shipment_id>#<materialno>` |

Key_ID alanları (`shipment_id`, `materialno`, `supplier_code`, `mip`, `USERID`) her yerde string tutulur ve eşleşme kesindir.

## Klasör yapısı

```
Logistic_AI/
├── agentcore/
│   ├── agentcore.json        # Runtime `agent`, yetkilendirici, envVars
│   ├── aws-targets.json      # Dağıtım hedefleri (ilk dağıtımda doldurulur)
│   ├── .env.local            # Yalnızca yerel ortam değişkenleri (sürüm kontrolünde yok)
│   └── cdk/                  # CLI'nin dağıttığı CDK uygulaması
├── app/
│   └── agent/
│       ├── main.py                   # AgentCore giriş noktası (tembel başlatma)
│       ├── identity.py               # Session_Token ile kimlik çözümleme
│       ├── agent_factory.py          # Strands Agent oluşturma (tembel)
│       ├── parse.py                  # İstek yükü ayrıştırma
│       ├── prompts/system_prompt.py  # Sistem istemi
│       ├── model/load.py             # Bedrock model yükleyici
│       ├── tools/                    # `guard` dekoratörü ve altı @tool
│       ├── logistic_ai_data/         # DataRepository (DynamoDB / bellek içi), anahtar normalizasyonu
│       ├── logistic_ai_shared_auth/  # Kimlik doğrulama, izin ve admin servisleri
│       ├── tests/                    # pytest testleri
│       ├── README.md                 # Backend ayrıntıları
│       └── pyproject.toml            # Yalnızca çalışma zamanı bağımlılıkları
├── config/
│   └── permissions.json      # Faz 1 rol → izin eşlemesi (sır değildir)
├── Data/                     # Excel kaynağı (sürüme eklenmez, aşağıya bakın)
├── docs/specs/logistics-ai-data-agent/   # Faz 2 tasarım belgeleri
├── scripts/
│   ├── ingest/               # Excel okuma, yükleme, tohumlama, rapor, run_ingest
│   ├── tests/                # Yükleme testleri
│   ├── pyproject.toml        # openpyxl yalnızca burada
│   ├── local/                # moto tabloları, env.example, uçtan uca yerel akış betiği
│   └── local_dev_check.sh    # Yerel geliştirme sunucusunu başlatıp bir kez çağırır
├── streamlit_client/         # Streamlit arayüzü (giriş, sohbet, Dashboard, Admin Panel)
└── README.md
```

## Ön koşullar

- Node.js 20.12 veya üzeri
- Python 3.12 veya üzeri
- uv
- AWS CDK (`npm install -g aws-cdk`)
- AgentCore_CLI 1.0.3 (`npm install -g @aws/agentcore@1.0.3`)
- Bedrock, AgentCore, DynamoDB ve Secrets Manager erişimi olan, yapılandırılmış AWS kimlik bilgileri (`aws sts get-caller-identity` ile doğrulayın)

## Veri yükleme (Ingestion)

Excel dosyası (`Data/*.xlsx`) `role_user` sheet'inde **düz metin şifreler** içerir. Bu nedenle `.gitignore` içindedir ve **sürüme eklenmez**. Başka kopyaları (örneğin `.kiro/Logistic_AI/Data/` altındakini) silin veya sürüm kontrolü dışında tutun. Şifreler hiçbir yere düz metin yazılmaz ve günlüğe/rapora girmez.

Yükleme aracı `scripts` dizininden çalıştırılır:

```bash
cd scripts
uv sync

# Varsayılan: dry-run. Hiçbir şey yazılmaz, AWS çağrısı yapılmaz. Sheet bazında rapor verir.
uv run python -m ingest.run_ingest

# Kullanıcı (role_user) ve izin (permissions) tohumlamasını da raporla
uv run python -m ingest.run_ingest --seed

# Gerçek yazma: yalnızca kullanıcı onayıyla ve tablolar oluşturulduktan sonra
uv run python -m ingest.run_ingest --apply --seed
```

- `--dry-run` varsayılandır. Gerçek yazma için `--apply` gerekir. Dosya yolu `--file` ile verilebilir.
- **`--apply` AWS kaynaklarına yazar.** Kullanıcı onayı gerektirir ve DynamoDB tablolarının (yukarıdaki şemalarla) önceden var olması şarttır. Tablo adları `LOGISTIC_AI_KB_TABLE`, `LOGISTIC_AI_USERS_TABLE`, `LOGISTIC_AI_PERMISSIONS_TABLE` değişkenlerinden okunur.
- Yükleme idempotenttir: ilgili sheet kayıtları `sheet-index` ile silinip aynı `load_id` ile yeniden yazılır. Bozuk JSON kayıtları atlanır ve raporlanır.
- `--seed`: `role_user` kayıtlarını argon2id özetiyle (`active=true`) ve `permissions` sheet'indeki başlangıç izinlerini yazar. Tekrar çalıştırma mevcut kullanıcı ve izin kayıtlarını ezmez (`attribute_not_exists`), böylece Admin Panel'deki değişiklikler korunur. `ALLOWED` değeri 0/1 dışında olan veya bilinmeyen kaynaklı izin satırları atlanır ve raporlanır.
- `role_user` ve `permissions` sheet'leri `kb` tablosuna yüklenmez.

## Roller, izinler ve Dashboard görünürlüğü

Roller: `SUPPLIER`, `MATERIAL_RESPONSIBLE`, `TRANSPORT_OFFICE`, `ADMIN`.

- İzinler `logistic-ai-permissions` tablosundadır ve iki tür kaynağı kapsar: `TABLE#<ad>` (`question1`…`question5`, `critical`, `summary_df`) ve `FUNCTION#<ad>` (altı Tool).
- Karar sırası: kullanıcı yok veya pasif ise ret; `role_user`/`permissions` kaynağı ise ret; kullanıcı bazlı kayıt; rol bazlı kayıt; kayıt yoksa ret (varsayılan ret). Kullanıcı bazlı kayıt rol bazlı kaydı geçersiz kılar. Sonuçlar en fazla 30 saniye önbelleklenir.
- Bir Tool'un çalışması için hem `FUNCTION` hem ilgili `TABLE` izni gerekir.
- Bu fazda izinli tüm roller ilgili tablolardaki tüm satırları görür. Satır bazlı kısıtlama kapsam dışıdır.
- **Dashboard** (`summary_df` tabanlı, donut chart ve KPI'lar): girişten sonra `TRANSPORT_OFFICE` ve `MATERIAL_RESPONSIBLE` için otomatik gösterilir ve `summary_df` tablo izni gerekir. `SUPPLIER` için gösterilmez. `ADMIN` için otomatik gösterilmez, Admin Panel'e yönlenir.

## Admin Panel kullanımı

Admin Panel yalnızca aktif `ADMIN` rolündeki kullanıcıya görünür. Tüm işlemler `AdminService` üzerinden yapılır ve denetim kaydına yazılır.

- **Kullanıcı listesi:** Kullanıcı adı, USERID, rol ve durum görünür. Şifre ve özet hiçbir zaman gösterilmez.
- **Aktif/pasif:** Anahtarla hesap etkinleştirilir veya devre dışı bırakılır. Admin kendi hesabını ve son aktif `ADMIN` hesabını pasif yapamaz.
- **İzinler:** Rol veya kullanıcı bazında tablo ve fonksiyon izni verilir ya da kaldırılır. Yalnızca bilinen kaynak adları kabul edilir. `role_user` ve `permissions` kaynakları reddedilir. `ADMIN` rolü atama işlemi yoktur.
- Değişiklikler sonraki izin denetimlerinde (en geç önbellek süresi sonunda) geçerli olur.

## Ajan Tool'ları

Her Tool, çağıran kullanıcının `FUNCTION` ve `TABLE` iznini denetler. Key_ID eksikse `missing_parameter`, kayıt yoksa `not_found`, izin yoksa `forbidden`, beklenmeyen hatada `error` döner.

| Tool | Parametre | Kaynak tablo |
| --- | --- | --- |
| `get_truck_location` | `shipment_id` | `question1` |
| `get_material_truck_allocation` | `materialno` | `question2` |
| `get_truck_route_info` | `shipment_id` (durak sırası sayısal artan) | `question3` |
| `get_delayed_truck` | yok | `question4` |
| `get_truck_tobearrived` | yok | `question5` |
| `get_critical_part_status` | `mip` | `critical` |

Sistem istemi (`app/agent/prompts/system_prompt.py`) Türkçe/İngilizce yanıt, doğru Tool seçimi, kısa ve Markdown tablo biçimli çıktı, eksik Key_ID için kullanıcıdan isteme ve veri uydurmama kurallarını içerir. Yetki kararı modele bırakılmaz.

## Ortam değişkenleri

Yalnızca değişken adları listelenmiştir. Değerleri yerelde ortamınıza veya `agentcore/.env.local` dosyasına (sürüm kontrolünde yok) girin. Gerçek değerleri commit etmeyin.

| Değişken | Zorunlu | Kullanan | Açıklama |
| --- | --- | --- | --- |
| `LOGISTIC_AI_KB_TABLE` | Evet | Backend, Client, Yükleme | `kb` tablosunun adı |
| `LOGISTIC_AI_USERS_TABLE` | Evet | Backend, Client, Yükleme | `users` tablosunun adı |
| `LOGISTIC_AI_PERMISSIONS_TABLE` | Evet | Backend, Client, Yükleme | `permissions` tablosunun adı |
| `LOGISTIC_AI_SESSION_SECRET_ID` | Biri zorunlu | Backend, Client | Session_Token imza anahtarını tutan Secrets Manager sırrının kimliği (önerilen) |
| `LOGISTIC_AI_SESSION_SECRET` | Biri zorunlu | Backend, Client | İmza anahtarı. Yalnızca yerel geliştirme için. `..._SECRET_ID` verilmezse kullanılır |
| `LOGISTIC_AI_MODEL_ID` | Evet | Backend | Bedrock modeli. `global.` önekli inference profile kimliği olmalıdır. Sabit kodlanmaz |
| `LOGISTIC_AI_AGENT_RUNTIME_ARN` | Evet (yerel modda hayır) | Client | Dağıtılmış ajan çalışma zamanının ARN'i |
| `LOGISTIC_AI_LOCAL_AGENT_URL` | Hayır | Client | Yalnızca yerel geliştirme: loopback `agentcore dev` adresi (bkz. Yerel çalıştırma) |
| `AWS_ENDPOINT_URL_DYNAMODB` | Hayır | Tümü | Yalnızca yerel geliştirme: DynamoDB'yi moto'ya yönlendirir |
| `LOGISTIC_AI_AWS_REGION` | Evet | Backend, Client | AWS bölgesi |
| `LOGISTIC_AI_IDLE_TIMEOUT_MINUTES` | Hayır | Client | Boşta kalma zaman aşımı (dakika, 1-480, varsayılan 30) |

Faz 1'den kalan `LOGISTIC_AI_USER_POOL_ID`, `LOGISTIC_AI_APP_CLIENT_ID`, `LOGISTIC_AI_PERMISSIONS_FILE` ve `LOGISTIC_AI_COGNITO_ENDPOINT_URL` yalnızca eski Cognito kodu tarafından okunur ve Faz 2 akışı için gerekmez.

Model kimliğini keşfetmek için (değer kodlanmaz, çıktıdaki kimliğe `global.` öneki eklenir):

```bash
aws bedrock list-foundation-models --by-provider Anthropic \
  --query "modelSummaries[?modelLifecycle.status=='ACTIVE'].{id:modelId,name:modelName}" \
  --output table --region <bölge>
```

Zorunlu bir değişken eksikse backend isteği kapalı başarısızlıkla (genel hata iletisi) reddeder. İstemci eksik değişken adlarını gösterir, değerleri göstermez.

### Dağıtım için backend ortam değişkenleri

- Dağıtılan backend'in yukarıdaki backend değişkenlerine ihtiyacı vardır. Bunları dağıtımdan önce `agentcore/agentcore.json` içindeki `agent` runtime'ının `envVars` listesine yerelde ekleyin. Sır değerlerini (`LOGISTIC_AI_SESSION_SECRET`) `envVars` içine yazmayın, Secrets Manager (`LOGISTIC_AI_SESSION_SECRET_ID`) kullanın.
- `UNIFIED_TRACES_DESTINATION_ENABLED` değerini `true` olarak `envVars` içinde tutun. Aksi halde izler CloudWatch günlük grubuna aktarılmaz.
- DynamoDB ve Secrets Manager erişimi IAM rolü elle düzenlenerek verilmez. İzinler runtime'ın `additionalPolicies` listesi ile bildirilir (politika dosyaları `app/agent/policies/` altında hazırlanır, `agentcore.json`'a eklenmesi kullanıcı onayına bağlıdır).

## Yerel çalıştırma

AWS kaynağı oluşturmadan, gerçek DynamoDB yerine `moto` ile çalışır. Mevcut DynamoDB kod yolları değişmez: boto3 `AWS_ENDPOINT_URL_DYNAMODB` değişkenini dikkate alır ve tüm depolar moto'ya yönlenir. Model çağrısı gerçek Bedrock'tur (geçerli AWS kimlik bilgileri gerekir, moto bunları yok sayar). `moto[server]` yalnızca `scripts/pyproject.toml` dev grubundadır.

> **Önemli:** 8080 numaralı bağlantı noktasını kullanmayın ve durdurmayın (IDE). Aşağıdaki sıra moto için 5001, backend için 8081 (meşgulse 8082), Streamlit için 8501 kullanır. Yalnızca kendi başlattığınız süreçleri durdurun.

Ortak ortam değişkenleri `scripts/local/env.example` dosyasındadır (yalnızca zararsız yerel değerler). Her terminalde `set -a; source scripts/local/env.example; set +a` ile yükleyin. Bedrock için gerçek AWS kimlik bilgilerinizi değiştirmeyin: `AWS_ACCESS_KEY_ID` ve `AWS_SECRET_ACCESS_KEY` değişkenlerini sahte değerlerle ezmeyin.

| Değişken | Açıklama |
| --- | --- |
| `AWS_ENDPOINT_URL_DYNAMODB` | `http://127.0.0.1:5001` (yalnızca loopback; tablo betiği başka değeri reddeder) |
| `AWS_DEFAULT_REGION`, `LOGISTIC_AI_AWS_REGION` | Örn. `us-east-1` |
| `LOGISTIC_AI_KB_TABLE`, `LOGISTIC_AI_USERS_TABLE`, `LOGISTIC_AI_PERMISSIONS_TABLE` | Tablo adları (varsayılanlar `logistic-ai-*`) |
| `LOGISTIC_AI_SESSION_SECRET` | En az 16 karakter (öneri: 32+). **Backend ve Streamlit için aynı değer** |
| `LOGISTIC_AI_MODEL_ID` | Yalnızca backend. `global.` önekli Anthropic Haiku/Sonnet profili (aşağıdaki komutla keşfedin) |
| `LOGISTIC_AI_LOCAL_AGENT_URL` | Yalnızca Streamlit. Örn. `http://127.0.0.1:8081/invocations`. Ayarlıysa SigV4 yerine yerel HTTP taşıması kullanılır ve `LOGISTIC_AI_AGENT_RUNTIME_ARN` gerekmez. Loopback dışı URL reddedilir |

```bash
# 0) Model kimliğini keşfet (salt okunur) ve ortamda ayarla
aws bedrock list-foundation-models --by-provider Anthropic \
  --query "modelSummaries[?modelLifecycle.status=='ACTIVE'].modelId" --output text --region us-east-1
export LOGISTIC_AI_MODEL_ID=global.<listeden-secilen-model-kimligi>

# 1) Terminal 1: yerel DynamoDB (moto)
cd scripts && uv sync
uv run moto_server -H 127.0.0.1 -p 5001

# 2) Terminal 2: tabloları oluştur (yalnızca loopback uç noktasında çalışır)
cd scripts && set -a; source local/env.example; set +a
uv run python local/create_local_tables.py

# 3) Excel yükleme: önce dry-run, sonra yerel moto'ya apply (şifreler argon2id ile özetlenir)
uv run python -m ingest.run_ingest --seed
uv run python -m ingest.run_ingest --seed --apply

# 4) Terminal 3: backend (proje kökünden; 8081 doluysa 8082 kullanın ve LOGISTIC_AI_LOCAL_AGENT_URL'yi buna göre ayarlayın)
set -a; source scripts/local/env.example; set +a
export LOGISTIC_AI_MODEL_ID=global.<listeden-secilen-model-kimligi>
agentcore dev --port 8081

# 5) Terminal 4: Streamlit
cd streamlit_client && uv sync
set -a; source ../scripts/local/env.example; set +a
uv run streamlit run app.py --server.port 8501 --server.headless true
#   Sağlık denetimi: curl http://127.0.0.1:8501/_stcore/health   (200 beklenir)
```

Giriş için Excel'deki `role_user` kullanıcılarını kullanın. Şifreler düz metin olarak yalnızca Excel'dedir.

Betikli uçtan uca doğrulama (giriş, soru, Admin ile izin kaldırma ve geri verme). moto ve `agentcore dev` açıkken, `LOGISTIC_AI_LOCAL_AGENT_URL` backend'in portuna ayarlı olarak çalıştırın:

```bash
cd streamlit_client
uv run --with openpyxl python ../scripts/local/e2e_local_flow.py
```

### Testler

```bash
cd app/agent && uv run pytest -q            # varsayılan olarak gerçek LLM testleri (-m llm) hariç
cd streamlit_client && uv run pytest -q
cd scripts && uv run pytest -q
cd app/agent && uv run pytest -m llm -q     # isteğe bağlı: gerçek Bedrock çağrısı yapar (maliyetli)
```

Varsayılan testler gerçek AWS çağrısı yapmaz (bellek içi uyarlayıcılar, `Stubber`, sahte DynamoDB). Sonuçlar için [TEST_REPORT.md](TEST_REPORT.md). Test komutlarını çalıştıran terminalde `AWS_ENDPOINT_URL_DYNAMODB` tanımlı olmamalıdır.

### Süreçleri durdurma

Her sunucuyu çalıştığı terminalde `Ctrl+C` ile durdurun (moto, `agentcore dev`, Streamlit). Arka planda başlattıysanız yalnızca kendi süreçlerinizi `kill <pid>` ile durdurun, bağlantı noktasına göre toplu `kill` yapmayın. 8080'deki sürece asla dokunmayın. moto verileri bellekte tutar: durdurunca yerel veri silinir ve adım 2-3 yeniden çalıştırılmalıdır.

## Açık Karar 1 durumu: AgentCore kimlik doğrulaması

> **Durum: çözülmedi, dağıtımı engelliyor.** `agentcore/agentcore.json` içindeki `agent` runtime'ı şu an `authorizerType: CUSTOM_JWT` (Cognito, yer tutuculu `customJwtAuthorizer`) ve `requestHeaderAllowlist: ["Authorization"]` ile yapılandırılmıştır. `role_user` tabanlı girişte Cognito token'ı oluşmadığından, bu ayar değiştirilmeden Faz 2 akışı dağıtılmış ortamda **çalışmaz**.

Tasarımın önerdiği yol (Seçenek A): yetkilendiriciyi **`AWS_IAM` (SigV4)** yapmak. Streamlit_Client `invoke_agent_runtime` ile imzalı çağırır, Session_Token payload'da taşınır, backend token'ı doğrular ve rol/izin/aktiflik bilgisini DynamoDB'den kendisi okur. Deployment yapılandırmasındaki tek değişiklik yetkilendirici türüdür (ve artık gereksiz olan `customJwtAuthorizer` bloğunun kaldırılması).

- `agentcore.json` bu karar kullanıcı tarafından onaylanmadan değiştirilmez. Kod, taşıma katmanından bağımsız (`IdentityResolver`) yazılmıştır.
- **Dağıtım (`agentcore deploy`), DynamoDB tablolarının oluşturulması ve `ingest --apply` için açık kullanıcı onayı gerekir.** Onay alınmadan hiçbiri çalıştırılmaz.
- Seçenek B (Cognito'yu koruyup kullanıcıları Cognito'ya aktarmak) kullanıcı durumunu iki yerde tutar ve 5 haneli şifreli kullanıcı için şifre sıfırlaması gerektirir. Ayrıntılar design.md'dedir.

Önerilen dağıtım sırası (hepsi onay gerektirir): (1) Açık Karar 1 kararı ve `agentcore.json` değişikliği, (2) DynamoDB tablolarının oluşturulması, (3) `ingest --apply --seed`, (4) `additionalPolicies` ekleme, (5) `agentcore deploy`, (6) çalışma zamanı ARN'ini yerelde `LOGISTIC_AI_AGENT_RUNTIME_ARN` değişkenine girme ve smoke testi.

## Dağıtım

```bash
agentcore deploy
```

Yalnızca yukarıdaki onay adımları tamamlandıktan sonra çalıştırın. İlk dağıtım yaklaşık 5-8 dakika sürer (varsayılan hedefi oluşturur, CDK'yı hazırlar ve CloudWatch Transaction Search'ü etkinleştirir). Sonraki dağıtımlar yaklaşık 5 dakika sürer. Ayrıntılı çıktı için `agentcore --debug deploy` kullanın.

## Dağıtılmış ajanı çağırma

```bash
agentcore invoke --runtime agent --session-id <kimlik> --payload '{"prompt":"..."}'
```

Oturum kimliği en az 33 karakter olmalıdır. Payload geçerli bir Session_Token içermelidir. Günlük kullanımda Streamlit_Client token'ı kendisi ekler.

## Durum, günlük ve izleme

```bash
agentcore status
agentcore logs runtime --tail
agentcore traces runtime list --since 15m
```

## Bilinen veri kalitesi bulguları (özet)

Excel analizinin tam listesi (15 madde): [docs/specs/logistics-ai-data-agent/design.md](docs/specs/logistics-ai-data-agent/design.md#veri-kalitesi-bulguları-excel-analizi).

- **Düz metin şifreler:** `role_user` tüm kullanıcılar için (ADMIN dahil) düz metin şifre içerir ve çoğu 6 haneli sayıdır (zayıf). Excel sürüme eklenmez. Şifre türü karışıktır (sayı/metin), sayıya çevrilen şifrelerde baştaki sıfırlar kaybolmuş olabilir ve 5 haneli bir şifre doğrulanmalıdır.
- **Tür tutarsızlıkları:** `USERID`, `supplier_code` ve `mip` tablolar arasında sayı/metin karışıktır. Hepsi string olarak normalize edilir. Tarihler `YYYY-MM-DD HH:MM:SS` metnine normalize edilir.
- **`summary_df` ile `question1` uyuşmuyor:** `summary_df` 18 tamamlanan sefer bildirirken `question1` tüm 46 seferi aktif gösterir. Dashboard yalnızca `summary_df`'e güvenir ve tutarsızlığı uyarı olarak kaydeder.
- **Formül yok:** Hiçbir sheet formül içermez. `Gecikme Oranı` kesir olarak saklıdır ve oran hesaplanarak gösterilir.
- **`critical` ile `question2` kesişmiyor:** `critical` içindeki malzemeler `question2`'de yoktur. `get_material_truck_allocation` bu malzemeler için "kayıt bulunamadı" döner. Bu bir veri uyuşmazlığıdır, hata değildir.
- **Kapsam farkı:** `critical` yalnızca 12 sefer ve 5 `mip` içerir.
- **Ondalık gösterim:** `question4.delay_time` ve JSON alanları karışık int/float, `critical.Gecikme_Suresi` metin olarak kesilmiştir. Gösterimde yuvarlama kuralı gerekir.
- **Boş değerler:** `question3` yalnızca son durak için `location_text` ve `laststop_explanation` doldurur. Boş değerler hata sayılmaz.
- **Diğer:** `question5.driver_phone` yer tutucudur. Başlıklarda yazım hataları vardır (`KrtiklikZaman`, `Keyiid_explanation`, `mikta`). İstek gereği adlar korunur. JSON kayıtlarının tamamı geçerlidir, ancak parse koruması yine de uygulanır.

## Sorun giderme

| Hata | Çözüm |
| --- | --- |
| 30 saniyelik çalışma zamanı başlatma aşımı (Runtime initialization time exceeded) | Ajanı tembel başlatın ve `from bedrock_agentcore.runtime import BedrockAgentCoreApp` içe aktarmasını kullanın. `from bedrock_agentcore import ...` ağır modülleri yükler. |
| Oturum kimliği 33 karakterden kısa (`runtimeSessionId ... length greater than or equal to 33`) | En az 33 karakterlik bir `--session-id` kullanın. |
| Model kimliği inference profile öneki olmadan (on-demand throughput not supported) | `LOGISTIC_AI_MODEL_ID` değerine `global.` gibi bir önek ekleyin. Model kimliğini `aws bedrock list-foundation-models` ile keşfedin. |
| Model erişimi reddedildi (AWS Marketplace izinleri) | Anthropic modelleri için hesap düzeyinde tek seferlik anlaşma gerekir. IDE terminalinde `enable_anthropic_models` çalıştırıp birkaç dakika bekleyin. Runtime rolüne Marketplace izni eklemeyin. |
| ARM64 wheel bulunamadı (uv install failed for all platform candidates) | AgentCore Runtime ARM64 üzerinde çalışır. ARM64 Linux wheel'i olmayan bağımlılığı çalışma zamanı bağımlılıklarından çıkarın. Test araçlarını `[dependency-groups] dev` altında tutun. |
| İzin reddedildi (Permission denied / AccessDenied) | `aws sts get-caller-identity` ile kimliği doğrulayın. Rol düzenlemek yerine izinleri projede (`additionalPolicies`) bildirin. Uygulama içinde "Bu işlem için yetkiniz yok" görülürse Admin Panel'den kullanıcının rol/kullanıcı izinlerini kontrol edin. |
| Dağıtılmış çağrı kimlik doğrulama hatasıyla reddediliyor | `agentcore.json` hâlâ `CUSTOM_JWT` ise Açık Karar 1 uygulanmamıştır. Yetkilendirici `AWS_IAM` olmalıdır (onay gerektirir). |
| 8081 numaralı bağlantı noktası kullanımda (Port 8081 in use) | `lsof -ti:8081 \| xargs kill -9` ile süreci durdurun veya `agentcore dev --port 8082` kullanın. 8080'deki süreci asla durdurmayın. |

## Güvenlik notları

- Sırlar (şifre, token, imza anahtarı) kaynak koda ve sürüm kontrolüne eklenmez. `.env*` dosyaları ve `Data/*.xlsx` `.gitignore` içindedir. Gerçek değerler yalnızca yerelde doldurulur.
- Şifreler argon2id ile özetlenir. Günlüklere ve raporlara şifre, özet veya token yazılmaz. Kullanıcı yok, şifre hatalı, pasif ve kilitli hesap aynı genel hata iletisini döndürür. 5 ardışık hatadan sonra hesap 15 dakika kilitlenir.
- IAM rolleri elle düzenlenmez (`aws iam put-role-policy` kullanılmaz). Gereken izinler `additionalPolicies` ile bildirilir ve `agentcore deploy` ile uygulanır.
- Yetkilendirme servis katmanında ve backend'de zorunlu olarak uygulanır. UI denetimleri yalnızca kolaylık içindir. Varsayılan davranış reddetmektir. İstek yükündeki `actorId` rol kaynağı değildir. Yetki reddi denetim kaydına yazılır.

## Gelecek kapsam (Faz 2 dışı)

- Bedrock Knowledge Base (vektör arama), Memory, Skills, MCP
- Satır bazlı veri kısıtlaması (örneğin tedarikçinin yalnızca kendi kayıtlarını görmesi)
- Excel'in günlük otomatik yüklenmesi (S3/zamanlanmış yükleme)
