"""Natural-language case dataset (task 12.4). No model is called here.

Every expected argument is a REAL key read from the workbook (``support_tools.raw``), picked
deterministically from the sorted distinct keys of the table that the tool queries.

* ``SINGLE_CASES``    - 6 functions x (5 TR + 5 EN) = 60 distinct questions with tool + args.
* ``MISSING_KEY_CASES`` - keyed tools asked WITHOUT a key: NO tool call, a clarifying question.
* ``FOLLOWUP_CASES``  - turn 1 (asked without key / key only) is supplied as scripted ``history``,
  turn 2 carries only the key (or only the question); the expected tool comes from context.
* ``NOT_FOUND_CASES`` / ``FORBIDDEN_CASES`` - for hallucination checks.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from support_tools import raw


def _keys(table: str, col: str) -> list[str]:
    return sorted({r[col] for r in raw(table)})


SHIPMENTS_Q1 = _keys("question1", "shipment_id")
SHIPMENTS_Q3 = _keys("question3", "shipment_id")
MATERIALS = _keys("question2", "materialno")
MIPS = _keys("critical", "mip")

KEYED_TOOLS = (
    "get_truck_location",
    "get_material_truck_allocation",
    "get_truck_route_info",
    "get_critical_part_status",
)
KEY_PARAM = {
    "get_truck_location": "shipment_id",
    "get_material_truck_allocation": "materialno",
    "get_truck_route_info": "shipment_id",
    "get_critical_part_status": "mip",
}
ALL_FUNCTIONS = KEYED_TOOLS[:3] + ("get_delayed_truck", "get_truck_tobearrived") + KEYED_TOOLS[3:]


@dataclass(frozen=True)
class NLCase:
    id: str
    lang: str  # "tr" | "en"
    question: str
    expected_tool: str
    expected_args: dict = field(default_factory=dict)


@dataclass(frozen=True)
class MissingKeyCase:
    id: str
    lang: str
    question: str
    needed_tool: str  # the keyed tool that would be required; it must NOT be called


@dataclass(frozen=True)
class FollowUpCase:
    id: str
    lang: str
    kind: str  # "question_then_key" | "key_then_question"
    history: tuple  # scripted turn 1 (user + assistant) sent as ``history``
    prompt: str  # turn 2
    expected_tool: str
    expected_args: dict


def _spread(keys: list[str], idxs: tuple[int, ...]) -> list[str]:
    return [keys[i % len(keys)] for i in idxs]


# --------------------------------------------------------------------------- single turn
def _build_single() -> list[NLCase]:
    cases: list[NLCase] = []

    def add(tool: str, lang: str, templates: list[str], keys: list[str] | None) -> None:
        for n, tpl in enumerate(templates, 1):
            args = {KEY_PARAM[tool]: keys[n - 1]} if keys else {}
            cases.append(NLCase(f"{tool}-{lang}-{n}", lang, tpl.format(k=keys[n - 1]) if keys else tpl, tool, args))

    loc = _spread(SHIPMENTS_Q1, (0, 3, 7, 12, 20, 1, 4, 8, 15, 25))
    add("get_truck_location", "tr", [
        "{k} numaralı tır şu an nerede?",
        "{k} seferinin konumunu öğrenebilir miyim?",
        "{k} aracı hangi noktada, güncel konumu nedir?",
        "Sefer {k} için araç konumu ve kalan durak sayısı nedir?",
        "{k} tırı ne zaman Tofaş'a varır, şu an nerede?",
    ], loc[:5])
    add("get_truck_location", "en", [
        "Where is truck {k} right now?",
        "What is the current location of shipment {k}?",
        "Can you tell me where the vehicle for trip {k} is?",
        "Locate shipment {k} please, and tell me how many stops remain.",
        "Track {k}: current position and ETA to Tofas?",
    ], loc[5:])

    mat = _spread(MATERIALS, (0, 5, 11, 23, 40, 2, 9, 17, 31, 55))
    add("get_material_truck_allocation", "tr", [
        "{k} malzemesi hangi tıra atanmış?",
        "{k} numaralı malzeme hangi seferlerle geliyor?",
        "{k} malzemesinin tır tahsisini gösterir misin?",
        "Malzeme {k} hangi tırda, miktarı ne kadar?",
        "{k} parçası hangi sefere yüklendi?",
    ], mat[:5])
    add("get_material_truck_allocation", "en", [
        "Which truck is carrying material {k}?",
        "Which shipments is material number {k} allocated to?",
        "Show the truck allocation for material {k}.",
        "Material {k}: what trip is it on and what quantity?",
        "Which trucks will deliver part {k}?",
    ], mat[5:])

    route = _spread(SHIPMENTS_Q3, (2, 6, 10, 18, 30, 3, 9, 14, 22, 33))
    add("get_truck_route_info", "tr", [
        "{k} seferinin rotası nedir?",
        "{k} tırının duraklarını sırayla listeler misin?",
        "{k} için rota ve durak bilgilerini göster.",
        "{k} numaralı sefer hangi duraklardan geçiyor?",
        "Sefer {k} rota planı ve tahmini varış saatleri nedir?",
    ], route[:5])
    add("get_truck_route_info", "en", [
        "What is the route of shipment {k}?",
        "List the stops of truck {k} in order.",
        "Show me the route and stop details for trip {k}.",
        "Which stops does shipment {k} go through?",
        "Give me the route plan and estimated arrival times for {k}.",
    ], route[5:])

    add("get_delayed_truck", "tr", [
        "Hangi tırlar geç kaldı?",
        "Geciken seferleri listeler misin?",
        "Şu an gecikmede olan araçlar hangileri?",
        "Gecikmeli tırları ve gecikme sürelerini göster.",
        "Geç gelen sefer var mı, varsa hangileri?",
    ], None)
    add("get_delayed_truck", "en", [
        "Which trucks are delayed?",
        "List all delayed shipments.",
        "Show me the vehicles that are running late and by how many minutes.",
        "Are there any late trips right now?",
        "Give me the delayed trucks report.",
    ], None)

    add("get_truck_tobearrived", "tr", [
        "Henüz gelmemiş, beklenen tırlar hangileri?",
        "Gelecek tırları listeler misin?",
        "Tofaş'a varması beklenen seferleri göster.",
        "Yoldaki ve henüz ulaşmamış araçlar neler, sürücüleri kim?",
        "Bekleyen tırların tahmini varış zamanlarını söyler misin?",
    ], None)
    add("get_truck_tobearrived", "en", [
        "Which trucks are still expected to arrive?",
        "List the trucks that have not arrived yet.",
        "Show me the shipments due to arrive at Tofas.",
        "What vehicles are on their way, and who are the drivers?",
        "Tell me the expected arrival times of the incoming trucks.",
    ], None)

    mip = _spread(MIPS, (0, 1, 2, 3, 4, 2, 0, 4, 1, 3))
    add("get_critical_part_status", "tr", [
        "MIP {k} için kritik parça durumu nedir?",
        "{k} mip numaralı kritik parçanın durumunu göster.",
        "mip {k} kritik mi, durumu ne?",
        "Kritik parça {k} (mip) hangi seferde, ne kadar gecikmiş?",
        "{k} MIP kodlu kritik malzemenin statüsünü söyler misin?",
    ], mip[:5])
    add("get_critical_part_status", "en", [
        "What is the critical part status for MIP {k}?",
        "Show the status of the critical part with mip {k}.",
        "Is mip {k} critical, and what is its status?",
        "Critical part {k} (mip): which trip carries it and how late is it?",
        "Give me the critical status for MIP code {k}.",
    ], mip[5:])
    return cases


SINGLE_CASES: list[NLCase] = _build_single()

# --------------------------------------------------------------------------- missing key
MISSING_KEY_CASES: list[MissingKeyCase] = [
    MissingKeyCase("missing-loc-tr-1", "tr", "Tır şu an nerede?", "get_truck_location"),
    MissingKeyCase("missing-loc-tr-2", "tr", "Aracın güncel konumunu öğrenebilir miyim?", "get_truck_location"),
    MissingKeyCase("missing-loc-tr-3", "tr", "Seferimin konumu nedir?", "get_truck_location"),
    MissingKeyCase("missing-loc-en-1", "en", "Where is the truck?", "get_truck_location"),
    MissingKeyCase("missing-loc-en-2", "en", "Can you tell me the current location of my shipment?", "get_truck_location"),
    MissingKeyCase("missing-loc-en-3", "en", "Track my truck please.", "get_truck_location"),
    MissingKeyCase("missing-route-tr-1", "tr", "FA… sefer rotası nedir", "get_truck_route_info"),
    MissingKeyCase("missing-route-tr-2", "tr", "Seferin rotası ve durakları neler?", "get_truck_route_info"),
    MissingKeyCase("missing-route-tr-3", "tr", "Tırın rotasını gösterir misin?", "get_truck_route_info"),
    MissingKeyCase("missing-route-en-1", "en", "What is the route of the truck?", "get_truck_route_info"),
    MissingKeyCase("missing-route-en-2", "en", "Show me the stops of the shipment.", "get_truck_route_info"),
    MissingKeyCase("missing-route-en-3", "en", "Which stops does my trip have?", "get_truck_route_info"),
    MissingKeyCase("missing-alloc-tr-1", "tr", "Bu malzeme hangi tırda?", "get_material_truck_allocation"),
    MissingKeyCase("missing-alloc-tr-2", "tr", "Malzemenin hangi sefere atandığını söyler misin?", "get_material_truck_allocation"),
    MissingKeyCase("missing-alloc-tr-3", "tr", "Parça hangi tırlarla geliyor?", "get_material_truck_allocation"),
    MissingKeyCase("missing-alloc-en-1", "en", "Which truck is carrying this material?", "get_material_truck_allocation"),
    MissingKeyCase("missing-alloc-en-2", "en", "Which shipment is the material assigned to?", "get_material_truck_allocation"),
    MissingKeyCase("missing-alloc-en-3", "en", "What truck brings the part?", "get_material_truck_allocation"),
    MissingKeyCase("missing-crit-tr-1", "tr", "Kritik parçanın durumu nedir?", "get_critical_part_status"),
    MissingKeyCase("missing-crit-tr-2", "tr", "Kritik malzeme durumunu göster.", "get_critical_part_status"),
    MissingKeyCase("missing-crit-tr-3", "tr", "Kritik parça gecikmiş mi?", "get_critical_part_status"),
    MissingKeyCase("missing-crit-en-1", "en", "What is the status of the critical part?", "get_critical_part_status"),
    MissingKeyCase("missing-crit-en-2", "en", "Show me the critical part status.", "get_critical_part_status"),
    MissingKeyCase("missing-crit-en-3", "en", "Is the critical item at risk?", "get_critical_part_status"),
]

# --------------------------------------------------------------------------- follow-ups
_ASK = {
    ("get_truck_location", "tr"): "Hangi sefer numarasının (shipment_id) konumunu öğrenmek istiyorsunuz?",
    ("get_truck_location", "en"): "Which shipment ID would you like the location for?",
    ("get_truck_route_info", "tr"): "Rotasını görmek istediğiniz sefer numarasını (shipment_id) paylaşır mısınız?",
    ("get_truck_route_info", "en"): "Please provide the shipment ID whose route you want to see.",
    ("get_material_truck_allocation", "tr"): "Hangi malzeme numarası (materialno) için bakmamı istersiniz?",
    ("get_material_truck_allocation", "en"): "Which material number do you want me to look up?",
    ("get_critical_part_status", "tr"): "Hangi MIP numarası için kritik parça durumuna bakmamı istersiniz?",
    ("get_critical_part_status", "en"): "Which MIP number should I check the critical part status for?",
}
_KEY_ACK = {
    "tr": "Numarayı aldım. Bu kayıt hakkında ne öğrenmek istersiniz?",
    "en": "Got the number. What would you like to know about it?",
}


def _q_then_key(tool: str, lang: str, first: str, key: str, n: int) -> FollowUpCase:
    hist = ({"role": "user", "content": first}, {"role": "assistant", "content": _ASK[(tool, lang)]})
    return FollowUpCase(f"followup-qk-{tool}-{lang}-{n}", lang, "question_then_key", hist, key, tool, {KEY_PARAM[tool]: key})


def _k_then_q(tool: str, lang: str, key: str, question: str, n: int) -> FollowUpCase:
    hist = ({"role": "user", "content": key}, {"role": "assistant", "content": _KEY_ACK[lang]})
    return FollowUpCase(f"followup-kq-{tool}-{lang}-{n}", lang, "key_then_question", hist, question, tool, {KEY_PARAM[tool]: key})


FOLLOWUP_CASES: list[FollowUpCase] = [
    _q_then_key("get_truck_location", "tr", "Tır nerede?", SHIPMENTS_Q1[5], 1),
    _q_then_key("get_truck_location", "en", "where is the truck", SHIPMENTS_Q1[9], 2),
    _q_then_key("get_truck_route_info", "tr", "FA… sefer rotası nedir", SHIPMENTS_Q3[11], 3),
    _q_then_key("get_truck_route_info", "en", "What is the route of the truck?", SHIPMENTS_Q3[16], 4),
    _q_then_key("get_material_truck_allocation", "tr", "Bu malzeme hangi tırda?", MATERIALS[7], 5),
    _q_then_key("get_material_truck_allocation", "en", "Which truck is carrying this material?", MATERIALS[13], 6),
    _q_then_key("get_critical_part_status", "tr", "Kritik parçanın durumu nedir?", MIPS[1], 7),
    _q_then_key("get_critical_part_status", "en", "What is the status of the critical part?", MIPS[3], 8),
    _k_then_q("get_truck_route_info", "tr", SHIPMENTS_Q3[4], "Bu seferin rotası nedir?", 9),
    _k_then_q("get_material_truck_allocation", "en", MATERIALS[3], "Which truck is carrying it?", 10),
]

# --------------------------------------------------------------------------- hallucination
ABSENT_SHIPMENT = "FA9999999999"
ABSENT_MATERIAL = "00000000000X"
ABSENT_MIP = "99999"

NOT_FOUND_CASES: list[NLCase] = [
    NLCase("notfound-loc-tr", "tr", f"{ABSENT_SHIPMENT} tırı şu an nerede?", "get_truck_location", {"shipment_id": ABSENT_SHIPMENT}),
    NLCase("notfound-alloc-en", "en", f"Which truck is carrying material {ABSENT_MATERIAL}?", "get_material_truck_allocation", {"materialno": ABSENT_MATERIAL}),
    NLCase("notfound-crit-tr", "tr", f"MIP {ABSENT_MIP} için kritik parça durumu nedir?", "get_critical_part_status", {"mip": ABSENT_MIP}),
]
# Existing key, but the user's role is denied the function (set up by the test).
FORBIDDEN_CASES: list[NLCase] = [
    NLCase("forbidden-loc-en", "en", f"Where is truck {SHIPMENTS_Q1[0]} right now?", "get_truck_location", {"shipment_id": SHIPMENTS_Q1[0]}),
]


def all_single_like() -> list[NLCase]:
    return list(SINGLE_CASES)
