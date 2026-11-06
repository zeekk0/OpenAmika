"""Small, explicit CLI catalogs. Never translate raw subprocess errors or config identifiers."""
import argparse


def language_from_args(argv=None):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--lang', choices=('en', 'ko'), default='en')
    return parser.parse_known_args(argv)[0].lang


def choose(lang, en, ko, **params):
    message = ko if lang == 'ko' else en
    return message.format(**params) if params else message


MESSAGES = {
    'language': ('diagnostic language (en or ko)', '안내 언어 (en 또는 ko)'),
    'check': ('report readiness without installing or starting services', '설치하거나 서비스를 시작하지 않고 준비 상태를 점검합니다'),
    'ready': ('result: ready', '결과: 준비됨'),
    'not_ready': ('result: fix the !! lines above (-- lines are informational)', '결과: 위의 !! 항목을 해결하세요 (-- 항목은 참고 정보입니다)'),
    'setup_missing': ('Not ready: run this script without --check to install what is missing.', '준비되지 않았습니다. 누락 항목을 설치하려면 --check 없이 이 스크립트를 실행하세요.'),
    'setup_retry': ('Fix the !! lines above and run this script again (finished steps are skipped).', '위의 !! 항목을 해결한 뒤 다시 실행하세요 (완료된 단계는 건너뜁니다).'),
    'setup_summary': ('OpenAmika setup summary ({seconds} s)', 'OpenAmika 설치 요약 ({seconds}초)'),
    'check_summary': ('{ok} ok · {warn} warning(s) · {err} problem(s). No models loaded. Local health endpoints may be queried.', '{ok}개 정상 · {warn}개 주의 · {err}개 문제. 모델은 로드하지 않습니다. 로컬 상태 확인 주소에 요청할 수 있습니다.'),
    'port_free': ('{port} free', '{port} 사용 가능'),
    'port_unknown': ('{port} is in use (ownership unknown) - that component cannot start; check the existing listener or change settings.json. No process was stopped', '{port} 사용 중 (소유 프로세스 확인 불가). 이 구성 요소를 시작할 수 없습니다. 기존 리스너를 확인하거나 settings.json의 포트를 변경하세요. 프로세스를 중지하지 않았습니다'),
}


def text(key, lang='en', **params):
    return choose(lang, *MESSAGES[key], **params)
