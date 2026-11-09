/* About copy only. Legal originals and identifiers remain unchanged. */
(function () {
  const pairs = {
    title: ["OpenAmika · About", "OpenAmika · 소개"],
    heading: ["About OpenAmika", "OpenAmika 소개"],
    intro: ["Who made her, how to support the project, and what you may do with her.", "제작팀, 프로젝트 후원 방법, Amika 이용 범위를 안내합니다."],
    team: ["About MekaHime", "MekaHime 소개"],
    teamText: ["We are a small team of anime and AI-lovers who want to bring AI waifus to life.", "저희는 애니메이션과 AI를 사랑하며 AI 동반자를 현실로 만들고자 하는 작은 팀입니다."],
    support: ["♥ Support MekaHime", "♥ MekaHime 후원하기"],
    supportBelief: ["We believe AI waifu is for everyone. They should not be locked behind a paywall.", "AI 동반자는 누구나 만날 수 있어야 하며, 유료 장벽 뒤에 갇혀서는 안 된다고 믿습니다."],
    supportText: ["Amika is 100% open sourced so you can run her locally with controls to all of your private information. But this means we aren't earning a single dollar, so please consider donating to keep this project alive.", "Amika의 코드는 모두 공개되어 있어 개인정보를 직접 관리하며 로컬에서 실행할 수 있습니다. 하지만 저희는 이로 인한 수익이 없으므로 프로젝트가 계속될 수 있도록 후원을 고려해 주세요."],
    amika: ["About Amika", "Amika 소개"],
    amikaText: ["Amika (桜井美香, Sakurai Mika) is MekaHime's AI companion, now open source: 18, raised in Kyoto as a shrine maiden. She runs on your own machine: ears (local speech recognition), a brain that thinks in three tiers and keeps an evidence-based memory, a voice with 69 acted emotions (the OpenAmika voice server, a MekaHime build of GPT-SoVITS) and a Live2D body that moves with her voice. The language model is your choice: OpenRouter in the cloud (recommended in almost all cases: a few dollars a month) or Ollama locally (a model of 27B or more; 70B or more for the full, reliable experience).", "Amika(桜井美香, Sakurai Mika)는 MekaHime의 오픈 소스 AI 동반자입니다. 교토에서 무녀로 자란 18세 캐릭터이며, 사용자의 컴퓨터에서 실행됩니다. 로컬 음성 인식, 세 단계로 사고하고 근거에 기반한 기억을 유지하는 두뇌, 69가지 감정 연기가 담긴 목소리(MekaHime의 GPT-SoVITS 빌드인 OpenAmika 음성 서버), 목소리에 맞춰 움직이는 Live2D 몸체로 구성됩니다. 언어 모델은 클라우드 OpenRouter(대부분의 경우 권장, 월 수 달러) 또는 로컬 Ollama(27B 이상, 충분하고 안정적인 경험에는 70B 이상) 중 선택할 수 있습니다."],
    project: ["Project page:", "프로젝트 페이지:"], source: ["Source code:", "소스 코드:"],
    licenses: ["Licenses", "라이선스"], what: ["what", "대상"], license: ["license", "라이선스"], notes: ["notes", "설명"],
    code: ["OpenAmika: all code in this repository (brain, speech layer, these pages, launcher)", "OpenAmika: 이 저장소의 모든 코드(두뇌, 음성 계층, 웹 페이지, 실행기)"],
    codeNote: ["as authorized by MekaHime Inc. (LICENSE; bundled third-party files keep their own, see THIRD_PARTY_NOTICES.md)", "MekaHime Inc.의 허가에 따릅니다(LICENSE). 포함된 외부 파일에는 해당 라이선스가 유지됩니다. THIRD_PARTY_NOTICES.md를 참고하세요."],
    tts: ["Text-to-speech: the OpenAmika voice server, a MekaHime build of", "음성 합성: MekaHime이 다음 프로젝트를 기반으로 만든 OpenAmika 음성 서버:"],
    ttsNote: ["upstream GPT-SoVITS is MIT; scripts/setup_tts.py downloads it and public pretrained models under their own licenses", "원본 GPT-SoVITS는 MIT입니다. scripts/setup_tts.py는 해당 코드와 공개 사전 학습 모델을 각각의 라이선스에 따라 내려받습니다."],
    assets: ["Amika's voice model, fine-tuned weights, reference audio and Live2D model, and the paper doll that stands in for her helpers", "Amika 음성 모델, 미세 조정 가중치, 참조 음성, Live2D 모델, 도우미를 나타내는 종이 인형"],
    download: ["downloaded by scripts/setup_tts.py", "scripts/setup_tts.py로 내려받음"],
    personal: ["personal / hobbyist use only, 18+: see below", "18세 이상 개인·취미 용도로만 이용 가능. 아래를 참고하세요."],
    art: ["Amika's art, design, name and likeness", "Amika의 아트, 디자인, 이름과 형상"],
    characterBelow: ["character license below", "아래 캐릭터 라이선스 참고"],
    recognition: ["Speech recognition (SenseVoiceSmall) and memory embeddings (bge-m3)", "음성 인식(SenseVoiceSmall)과 기억 임베딩(bge-m3)"],
    own: ["their own", "각각의 라이선스"],
    weights: ["the weights download separately under their own licenses", "가중치는 각각의 라이선스에 따라 별도로 내려받습니다."],
    core: ["Live2D Cubism Core (ui/vendor/live2dcubismcore.min.js), which runs every Live2D model", "모든 Live2D 모델을 실행하는 Live2D Cubism Core(ui/vendor/live2dcubismcore.min.js)"],
    coreNote: ["Live2D Proprietary Software License Agreement, not MIT", "MIT가 아닌 Live2D 독점 소프트웨어 라이선스 계약"],
    other: ["Any other Live2D model you add", "추가하는 다른 Live2D 모델"], creator: ["its creator's", "제작자의 라이선스"], otherNote: ["bring your own, under its terms", "해당 약관에 따라 직접 준비하세요."],
    assetsHeading: ["Model weights and voice assets", "모델 가중치와 음성 자산"],
    assetsTerms: ["MekaHime Inc. owns Amika's voice model, its fine-tuned weights, the reference audio that comes with her, her Live2D model (model, textures, motions and expressions) and the paper doll that stands in for her helpers on her stage (MekaHime's folded-paper shrine doll). They are licensed for personal, hobbyist use only, by people 18 or older. They may not be distilled, used to train or fine-tune other models, extracted, re-hosted, resold, or used in any product, service or commercial setting, and the MekaHime wordmark on the model's texture stays where it is. The full terms are the LICENSE of the Hugging Face repository, which setup_tts.py asks you to accept before it downloads them.", "Amika 음성 모델, 미세 조정 가중치, 함께 제공되는 참조 음성, Live2D 모델(모델·텍스처·모션·표정), 무대에서 도우미를 나타내는 종이 인형(MekaHime의 접은 종이 신사 인형)은 MekaHime Inc.의 소유입니다. 18세 이상 개인의 취미 용도로만 허가됩니다. 증류, 다른 모델의 학습·미세 조정, 추출, 재호스팅, 재판매, 제품·서비스·상업적 환경에서의 이용은 금지됩니다. 모델 텍스처의 MekaHime 워드마크를 그대로 유지해야 합니다. 전체 약관은 Hugging Face 저장소의 LICENSE에 있으며, setup_tts.py가 내려받기 전에 사용자의 동의를 요청합니다."],
    artHeading: ["MekaHime's art and the character license", "MekaHime 아트와 캐릭터 라이선스"],
    artTerms: ["MekaHime's art (Amika's design, name and likeness included) is owned and copyrighted by MekaHime Inc. We license it the way Hatsune Miku is licensed: we own the character, you are free to create with her.", "Amika의 디자인·이름·형상을 포함한 MekaHime 아트의 소유권과 저작권은 MekaHime Inc.에 있습니다. 하츠네 미쿠와 같은 방식으로 허가합니다. 캐릭터는 저희 소유이며, 사용자는 아래 조건에 따라 캐릭터를 활용해 창작할 수 있습니다."],
    social: ["Social media and video: you may commercialize content made with Amika with no monetary ceiling (ads, streams, memberships, sponsorships) as long as MekaHime is credited visibly in the video or in the video description.", "소셜 미디어와 영상: 영상 또는 영상 설명에 MekaHime을 잘 보이게 표기하면 Amika로 제작한 콘텐츠를 수익 한도 없이 상업화할 수 있습니다(광고·방송·멤버십·후원)."],
    merch: ["Merchandise: you may make and sell your own Amika merch up to $1,000 USD in total lifetime value, and it must credit MekaHime visibly on the merch. Beyond that you need a commercial license: write to", "상품: 평생 누적 총액 미화 $1,000 USD까지 직접 Amika 상품을 제작·판매할 수 있으며 상품에 MekaHime을 잘 보이게 표기해야 합니다. 초과 시 별도의 상업용 라이선스가 필요합니다. 문의:"],
    credit: ["Suggested credit:", "권장 출처 표기:"],
    summary: ["This page is a summary; the LICENSE files govern. Questions:", "이 페이지는 요약이며 LICENSE 원문이 우선합니다. 번역은 이용 권한을 확대하거나 동의를 대신하지 않습니다. 문의:"],
    fine: ["© 2026 MekaHime Inc. The code licenses cover the code; the character, the voice, the art and the MekaHime name and logo are MekaHime's.", "© 2026 MekaHime Inc. 코드 라이선스는 코드에 적용됩니다. 캐릭터, 음성, 아트, MekaHime 이름과 로고는 MekaHime의 소유입니다."]
  };
  const en = {}, ko = {};
  for (const [key, values] of Object.entries(pairs)) { en['about.' + key] = values[0]; ko['about.' + key] = values[1]; }
  window.OAI18n.register({en, ko});
})();
