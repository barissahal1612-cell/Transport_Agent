# Logistics AI Assistant (Faz 1: Kimlik Doğrulama ve Yetkilendirme)

## Proje amacı

Bu proje, lojistik süreçleri için bir yapay zekâ asistanının kimlik doğrulama ve yetkilendirme temelini kurar. Kullanıcılar Amazon Cognito ile giriş yapar. Cognito grupları (`SUPPLIER`, `MATERIAL_RESPONSIBLE`, `TRANSPORT_OFFICE`) kullanıcının rolünü belirler. Amazon Bedrock AgentCore Runtime üzerinde çalışan Strands ajan iskeleti (Agent_Backend), isteği doğrular, yetkiyi denetler ve Faz 1'de model çağırmadan sabit bir yer tutucu yanıt döndürür.

Faz 1 kapsamı: giriş/çıkış, oturum yönetimi (boşta kalma zaman aşımı dahil), rol tabanlı yetkilendirme, denetim kaydı ve yer tutucu sohbet yanıtı.

## Mimari ve dağıtım topolojisi

```
Kullanıcı ──► Streamlit_Client ──► Cognito (USER_PASSWORD_AUTH)
                  │                      │ access token (cognito:groups içerir)
                  ▼                      ▼
        AgentCore Runtime (`agent`)  ◄── Authorization: Bearer <access token>
          1. AgentCore JWT authorizer (customJWTAuthorizer: discoveryUrl + allowedClients)
          2. Agent_Backend token'ı yeniden doğrular (imza/JWKS, exp, iss, token_use, client_id)
          3. Rol yalnızca doğrulanmış `cognito:groups` claim'inden türetilir
          4. Authorizer (varsayılan olarak reddet) `chat:invoke` iznini denetler
          5. Yer tutucu ajan sabit yanıtı akış olarak döndürür
```

- **Streamlit_Client** yerelde (veya ayrı bir sunucuda) çalışır. Cognito'dan **access token** alır ve Bearer token olarak gönderir.
- **Agent_Backend** AgentCore Runtime'da `agent` adıyla çalışır. Backend, Cognito **access token**'ını doğrular (`expected_token_use="access"`). Ayrıntılar için `app/agent/README.md` dosyasına bakın. ID token Bearer olarak gönderilirse reddedilir (`wrong_token_use`).
- `agentcore.json` içindeki `requestHeaderAllowlist: ["Authorization"]` ayarı, `Authorization` başlığının çalışma zamanına iletilmesini sağlar. Dağıtılmış çalışma zamanında başlığın gerçekten iletildiği ilk dağıtımdan sonra doğrulanmalıdır. Başlık yoksa backend `unauthenticated` döndürür (kapalı başarısızlık).
- Paylaşılan doğrulama ve yetkilendirme kodu `app/agent/logistic_ai_shared_auth` paketindedir. Hem backend hem istemci bu paketi kullanır.

## Klasör yapısı

```
Logistic_AI/
├── agentcore/
│   ├── agentcore.json        # Runtime `agent`, customJWTAuthorizer, envVars
│   ├── aws-targets.json      # Dağıtım hedefleri (ilk dağıtımda doldurulur)
│   ├── .env.local            # Yalnızca yerel ortam değişkenleri (sürüm kontrolünde yok)
│   └── cdk/                  # CLI'nin dağıttığı CDK uygulaması
├── app/
│   └── agent/
│       ├── main.py                   # AgentCore giriş noktası (tembel başlatma)
│       ├── parse.py                  # İstek yükü ayrıştırma
│       ├── placeholder_agent.py      # Yer tutucu Strands ajanı
│       ├── logistic_ai_shared_auth/  # Paylaşılan TokenVerifier ve Authorizer
│       ├── tests/                    # pytest testleri
│       ├── README.md                 # Backend ayrıntıları
│       └── pyproject.toml            # Yalnızca çalışma zamanı bağımlılıkları
├── config/
│   └── permissions.json      # Rol → izin eşlemesi (sır değildir)
├── scripts/
│   └── local_dev_check.sh    # Yerel geliştirme sunucusunu başlatıp bir kez çağırır
├── streamlit_client/         # Streamlit arayüzü (giriş, oturum, sohbet)
└── README.md
```

## Ön koşullar

- Node.js 20.12 veya üzeri
- Python 3.12 veya üzeri
- uv
- AWS CDK (`npm install -g aws-cdk`)
- AgentCore_CLI 1.0.3 (`npm install -g @aws/agentcore@1.0.3`)
- Bedrock ve AgentCore erişimi olan, yapılandırılmış AWS kimlik bilgileri (`aws sts get-caller-identity` ile doğrulayın)

## Cognito kurulumu

1. **Kullanıcı havuzu oluşturun** (Amazon Cognito → User pools). Kullanıcı adı ile oturum açmayı etkinleştirin.
2. **App Client oluşturun.** İstemci sırrı (client secret) olmayan bir genel istemci oluşturun ve `ALLOW_USER_PASSWORD_AUTH` (`USER_PASSWORD_AUTH`) akışını etkinleştirin. `ALLOW_REFRESH_TOKEN_AUTH` da açık olmalıdır.
3. **Üç grup oluşturun:** `SUPPLIER`, `MATERIAL_RESPONSIBLE` ve `TRANSPORT_OFFICE`. Her kullanıcıyı uygun gruba ekleyin. Rol, access token içindeki `cognito:groups` claim'inden okunur.
4. **`customJWTAuthorizer` değerlerini yerelde doldurun.** `agentcore/agentcore.json` içinde şu yer tutucular bulunur ve gerçek değerlerle yalnızca yerel kopyada değiştirilmelidir (gerçek değerleri commit etmeyin):

| Yer tutucu | Yerine gelecek değer |
| --- | --- |
| `REGION_PLACEHOLDER` | Kullanıcı havuzunun AWS bölgesi |
| `POOL_ID_PLACEHOLDER` | Cognito kullanıcı havuzu kimliği |
| `APP_CLIENT_ID_PLACEHOLDER` | App Client kimliği (`allowedClients` içinde) |

`discoveryUrl` biçimi: `https://cognito-idp.<bölge>.amazonaws.com/<havuz-kimliği>/.well-known/openid-configuration`.

## Ortam değişkenleri

Yalnızca değişken adları listelenmiştir. Değerleri yerelde ortamınıza veya `agentcore/.env.local` dosyasına (sürüm kontrolünde yok) girin.

| Değişken | Zorunlu | Kullanan | Açıklama |
| --- | --- | --- | --- |
| `LOGISTIC_AI_USER_POOL_ID` | Evet | Backend, Client | Cognito kullanıcı havuzu kimliği |
| `LOGISTIC_AI_APP_CLIENT_ID` | Evet | Backend, Client | İzin verilen tek App Client kimliği |
| `LOGISTIC_AI_AWS_REGION` | Evet | Backend, Client | Kullanıcı havuzunun bölgesi |
| `LOGISTIC_AI_AGENT_RUNTIME_ARN` | Evet | Client | Dağıtılmış ajan çalışma zamanının ARN'i |
| `LOGISTIC_AI_IDLE_TIMEOUT_MINUTES` | Hayır | Client | Boşta kalma zaman aşımı (dakika, 1-480, varsayılan 30) |
| `LOGISTIC_AI_PERMISSIONS_FILE` | Hayır | Backend, Client | İzin JSON dosyasının yolu. Varsayılan: `config/permissions.json` |
| `LOGISTIC_AI_COGNITO_ENDPOINT_URL` | Hayır | Client | Cognito uç noktasını geçersiz kılar (yerel test/taklit için) |

Zorunlu bir değişken eksikse veya izin dosyası geçersizse backend her isteği kapalı başarısızlıkla (genel `internal_error` iletisi) reddeder. İstemci eksik değişken adlarını gösterir, değerleri göstermez.

### Dağıtım için backend ortam değişkenleri

- Dağıtılan backend'in `LOGISTIC_AI_USER_POOL_ID`, `LOGISTIC_AI_APP_CLIENT_ID` ve `LOGISTIC_AI_AWS_REGION` değerlerine ihtiyacı vardır. Bunları dağıtımdan önce `agentcore/agentcore.json` içindeki `agent` runtime'ının `envVars` listesine yerelde ekleyin. Bunlar sır olmayan kimliklerdir ve yerelde doldurulur, commit edilmez.
- `UNIFIED_TRACES_DESTINATION_ENABLED` değerini `true` olarak `envVars` içinde tutun. Aksi halde izler CloudWatch günlük grubuna aktarılmaz.
- **İzin dosyası CodeZip dışındadır.** `config/permissions.json`, CodeZip `codeLocation` dizininin (`app/agent`) dışındadır ve pakete girmez. Dağıtılan çalışma zamanı için dosyanın bir kopyasını `app/agent` altına (örneğin `app/agent/config/permissions.json`) koyun ve `envVars` içinde `LOGISTIC_AI_PERMISSIONS_FILE` değişkenini bu kopyanın çalışma zamanındaki yoluna ayarlayın. Kopya olmadan çalışma zamanı izin dosyasını bulamaz ve istekler reddedilir.

## Yerel çalıştırma

> **Önemli:** 8080 numaralı bağlantı noktasını kullanmayın ve durdurmayın. Bu bağlantı noktası IDE tarafından kullanılır. Her zaman 8081 kullanın (meşgulse 8082).

Backend ortam değişkenlerini (`LOGISTIC_AI_USER_POOL_ID`, `LOGISTIC_AI_APP_CLIENT_ID`, `LOGISTIC_AI_AWS_REGION`) ayarladıktan sonra:

```bash
# Terminal 1: yerel geliştirme sunucusu (headless)
agentcore dev --port 8081

# Terminal 2: tek istek gönder
agentcore invoke --runtime agent --local --port 8081 --payload '{"prompt":"..."}'
```

Geçerli bir Bearer token olmadan yanıt `unauthenticated` olur. Tek komutla denemek için `scripts/local_dev_check.sh` kullanılabilir.

Streamlit_Client:

```bash
cd streamlit_client
uv sync
uv run streamlit run app.py --server.port 8501
```

Streamlit için 8080 yerine başka bir bağlantı noktası (örneğin 8501) seçin. İstemci için `LOGISTIC_AI_*` değişkenlerinin (en az ilk dördü) ayarlı olması gerekir.

Testler:

```bash
cd app/agent && uv run pytest
cd streamlit_client && uv run pytest
```

## Dağıtım

Dağıtımdan önce `agentcore.json` yer tutucularını ve `envVars` girdilerini yerelde doldurun (Cognito kurulumu ve ortam değişkenleri bölümleri).

```bash
agentcore deploy
```

İlk dağıtım yaklaşık 5-8 dakika sürer (hesap/bölgeden varsayılan hedefi oluşturur, CDK'yı hazırlar ve CloudWatch Transaction Search'ü etkinleştirir). Sonraki dağıtımlar yaklaşık 5 dakika sürer. Ayrıntılı çıktı için `agentcore --debug deploy` kullanın. Dağıtımdan sonra çalışma zamanı ARN'ini `LOGISTIC_AI_AGENT_RUNTIME_ARN` değişkenine yerelde girin.

## Dağıtılmış ajanı çağırma

```bash
agentcore invoke --runtime agent --session-id <kimlik> --payload '{"prompt":"..."}'
```

Oturum kimliği en az 33 karakter olmalıdır. `agent` runtime'ı JWT authorizer ile korunduğundan geçerli bir Bearer access token gerekir. Token'sız çağrılar reddedilir. Günlük kullanımda Streamlit_Client token'ı kendisi ekler.

## Durum, günlük ve izleme

```bash
agentcore status
agentcore logs runtime --tail
agentcore traces runtime list --since 15m
```

## Sorun giderme

| Hata | Çözüm |
| --- | --- |
| 30 saniyelik çalışma zamanı başlatma aşımı (Runtime initialization time exceeded) | Ajanı tembel başlatın ve `from bedrock_agentcore.runtime import BedrockAgentCoreApp` içe aktarmasını kullanın. `from bedrock_agentcore import ...` ağır modülleri yükler. |
| Oturum kimliği 33 karakterden kısa (`runtimeSessionId ... length greater than or equal to 33`) | En az 33 karakterlik bir `--session-id` kullanın. |
| Model kimliği inference profile öneki olmadan (on-demand throughput not supported) | Model kimliğine `global.` gibi bir önek ekleyin (örneğin `global.anthropic.claude-...`). Faz 1'de model çağrılmaz, bu hata sonraki fazlar için geçerlidir. |
| ARM64 wheel bulunamadı (uv install failed for all platform candidates) | AgentCore Runtime ARM64 üzerinde çalışır. ARM64 Linux wheel'i olmayan bağımlılığı çalışma zamanı bağımlılıklarından çıkarın. Test araçlarını `[dependency-groups] dev` altında tutun. |
| İzin reddedildi (Permission denied / AccessDenied) | `aws sts get-caller-identity` ile kimliği ve IAM izinlerini doğrulayın. Rol düzenlemek yerine izinleri projede (`additionalPolicies`) bildirin. Uygulama içinde "Bu işlem için yetkiniz yok" görülürse kullanıcının grubunu ve `config/permissions.json` içindeki `chat:invoke` iznini kontrol edin. |
| 8081 numaralı bağlantı noktası kullanımda (Port 8081 in use) | `lsof -ti:8081 \| xargs kill -9` ile süreci durdurun veya `agentcore dev --port 8082` kullanın. 8080'deki süreci asla durdurmayın. |

Ek ipuçları: her istek `unauthenticated` dönüyorsa Bearer token'ın **access token** olduğunu (ID token olmadığını) ve `requestHeaderAllowlist` ayarını kontrol edin. Her istek `internal_error` dönüyorsa zorunlu `LOGISTIC_AI_*` değişkenlerini ve izin dosyası yolunu kontrol edin.

## Güvenlik notları

- Sırlar (şifre, token, istemci sırrı) kaynak koda ve sürüm kontrolüne eklenmez. `.env*` dosyaları `.gitignore` içindedir. Gerçek Cognito kimlikleri yalnızca yerelde doldurulur.
- IAM rolleri elle düzenlenmez (`aws iam put-role-policy` kullanılmaz). Gereken izinler proje yapılandırmasında bildirilir ve `agentcore deploy` ile uygulanır.
- Yetkilendirme Agent_Backend'de zorunlu olarak uygulanır. Streamlit_Client'taki UI denetimleri yalnızca kolaylık içindir. Backend token'ı yeniden doğrular, rolü yalnızca doğrulanmış `cognito:groups` claim'inden türetir ve varsayılan olarak reddeder. İstek yükündeki `actorId` rol kaynağı değildir.
- Yetki reddi denetim kaydına yazılır. Günlüklere token veya şifre yazılmaz.

## Gelecek kapsam (Faz 1 dışı)

- Amazon Bedrock model çağrıları (Faz 1'de ajan model çağırmaz, sabit yer tutucu yanıt döner)
- Tools
- Memory: `agentMemory` desteği Faz 1'de kaldırılmıştır ve gelecek kapsamdır
- Skills
- MCP
