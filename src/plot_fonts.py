"""Select an installed Korean font, or an explicitly supplied font file."""
import os
from pathlib import Path
from matplotlib import font_manager

def korean_font():
    supplied = os.environ.get('SEOUL_FONT_PATH')
    if supplied:
        path = Path(supplied).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f'한글 글꼴 파일이 없습니다: {path}')
        font_manager.fontManager.addfont(str(path))
        return font_manager.FontProperties(fname=str(path)).get_name()
    installed = {f.name for f in font_manager.fontManager.ttflist}
    for name in ('Apple SD Gothic Neo', 'Malgun Gothic', 'NanumGothic',
                 'Noto Sans CJK KR', 'Noto Sans KR', 'NanumMyeongjo'):
        if name in installed:
            return name
    raise RuntimeError('한글 글꼴이 필요합니다. 나눔고딕을 설치하거나 SEOUL_FONT_PATH에 글꼴 파일을 지정하세요.')
