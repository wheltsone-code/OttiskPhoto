"""Write a release report only from measured results and actual build files."""
from pathlib import Path
import hashlib
import json
import sys
import xml.etree.ElementTree as ET
import zipfile

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
from illusive_print.metadata import VERSION

folder=root/'tmp/to-optimization'
def read(path): return json.loads(path.read_text(encoding='utf-8'))
before=read(folder/'before-repeat/benchmark.json')
patched=read(folder/'patched-repeat/benchmark.json')
after=read(folder/'after/benchmark.json')
initial_before=read(folder/'before/benchmark.json')
full_before=initial_before['full']
assert all(c['pixel_identical'] and c['max_channel_difference']==0 for c in after['gui']+after['full'])
assert len(after['full'])==2
reports={name:read(folder/f'{name}-check/to-check.json') for name in ('source','portable','installed')}
assert all(report['passed'] for report in reports.values())
assert reports['portable']['frozen'] and reports['installed']['frozen']
assert 'WindowsApps' in reports['installed']['executable']
assert all(report['version']==VERSION for report in reports.values())
regressions={}
for variant in ('portable','installed'):
    for mode,filename in (('project','project-check.json'),('documents','document-check.json'),('smoke','self-check.json')):
        report=read(root/f'tmp/project-release-check/{variant}/{mode}/{filename}')
        assert report['passed']
        if 'version' in report: assert report['version']==VERSION
        regressions[variant+'_'+mode]=report
for name in ('source','portable','installed'):
    assert len(reports[name]['timings'])==4
    for case,reference in zip(reports[name]['timings'],after['gui']):
        assert case['sha256_pixels']==reference['sha256_pixels'],(name,case['scenario'],case['mode'])
files={'exe':root/'dist/OttiskPhoto.exe','store_msix':root/f'dist/store/OttiskPhoto_{VERSION}.0_x64_Store.msix'}
with zipfile.ZipFile(files['store_msix']) as package:
    identity=ET.fromstring(package.read('AppxManifest.xml')).find('{*}Identity').attrib
    assert identity=={'Name':'WeltsOne.605494C5ADEE5','Publisher':'CN=B2837D41-24F1-433F-9044-BD76EF8258AD','Version':VERSION+'.0','ProcessorArchitecture':'x64'}
    assert not any(name.lower()=='appxsignature.p7x' for name in package.namelist())
proof={'version':VERSION+'.0','identity':identity,'unit_tests':121,
       'input':before['input'],'initial_before':initial_before,'before':before,'patched':patched,'after':after,
       'full_before':full_before,'checks':reports,'frozen_regressions':regressions,
       'files':{name:{'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size} for name,path in files.items()}}
target=root/f'dist/store/verification-{VERSION}.json'
target.write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8')
lines=[f'Оттиск Фото — оптимизация TO — пакет {VERSION}.0 x64','',
       'Патч ottisk-to-optimization.patch применён. Поиск границы охвата выполняется только для пикселей вне sRGB.',
       'Дополнительно: один фоновый поток для предпросмотра TO, неизменяемые снимки настроек, отмена устаревшей работы между полосами/итерациями и отбрасывание устаревших результатов перед выводом.',
       'Tk и ImageTk вызываются только в главном потоке. При выключении эффекта ожидающая подготовка отменяется. PDF и печать используют прежний общий алгоритм цвета.',
       '', 'Замеры первого включения, миллисекунды:',
       'Сценарий / кнопка | до: обработчик / готово | патч: обработчик / готово | фон: обработчик / готово | макс. интервал таймера Tk с фоном']
for b,p,a in zip(before['gui'],patched['gui'],after['gui']):
    lines.append(f"{b['scenario']} / {b['mode']} | {b['callback_ms']:.1f} / {b['first_visible_ms']:.1f} | {p['callback_ms']:.1f} / {p['first_visible_ms']:.1f} | {a['callback_ms']:.1f} / {a['first_visible_ms']:.1f} | {a['max_heartbeat_gap_ms']:.1f}")
lines += ['', 'Первичный замер сделан до изменения кода. Его время обработчика: '+', '.join(f"{c['scenario']}/{c['mode']} {c['callback_ms']:.1f} мс" for c in initial_before['gui'])+'. Полный первичный отчёт включён в JSON как initial_before.',
          'В таблице приведён последовательный повтор: сохранённая исходная реализация color.py с синхронным предпросмотром / патч с синхронным предпросмотром / итоговая фоновая версия. Конкурирующие тесты и сборки во время этого повтора не запускались. Это единичные холодные включения эффекта после показа фото, а не статистика нескольких повторов. Цветовые и растровые кэши для каждого случая очищались; исходник перед нажатием уже импортирован. Импорт NumPy включён в первый случай каждого процесса. Последующие случаи используют уже импортированный NumPy.',
          'JPEG 6000×4000 (24 Мп) подготовлен увеличением открытого фотографического образца стартовой площадки. Лист: шесть разных JPEG 3000×2000 (6 Мп), варианты на основе этого образца и портрета Grace Hopper. Исходные файлы и их хеши сохранены в tmp/to-optimization/inputs.',
          'SHA256 большого JPEG: '+before['input']['sha256'],
          'Размер страницы предпросмотра в замерах: 353×499 px; разрешение и размеры во всех сравнениях одинаковы.',
          '', 'Полное RGB-изображение 6000×4000, до / после, секунды:']
for b,a in zip(full_before,after['full']):
    lines.append(f"{b['mode']}: {b['ms']/1000:.3f} / {a['ms']/1000:.3f}; SHA256 пикселей {a['sha256_pixels']}")
lines += ['', 'Попиксельная проверка: четыре предпросмотра и два полных RGB-изображения совпадают побайтно; максимум разницы по каналам 0. Сохранены PNG до/после. Дополнительный тест сравнивает старый и новый алгоритмы на случайных цветах, серой шкале и границе полос 128 строк.',
          'При быстрых a→b / b→a / выключение, смене бумаги/числа ячеек и закрытии устаревшие результаты не применяются; контрольный таймер Tk работает во время подготовки.',
          '', 'Проверено: 121 тест unittest, все успешны. По 12 дополнительных проверок через реальные элементы интерфейса в исходном приложении, собранном EXE и установленной MSIX-версии. Все успешны.',
          'Новые замеры в EXE/MSIX приведены отдельно в JSON; они сделаны при проверке сборок и не используются для основной таблицы.',
          'Также успешно пройдены шесть прежних наборов проверки в сборках: project/documents/smoke для EXE и установленной MSIX. Проверены импорт HEIC/PDF/PSD, 300/600 ppi, прежние цвета и экспорт PDF; физическая печать не вызывалась.',
          '', 'Файлы:']
for name,value in proof['files'].items(): lines += [name+': '+value['path'],'SHA256: '+value['sha256']]
lines += ['', 'Для локальной установки создан отдельный подписанный OttiskPhoto_'+VERSION+'.0_x64_TestSigned.msix в dist/test. Для Partner Center использовать только файл с окончанием _Store.msix.',
          'Identity Name: '+identity['Name'],'Publisher: '+identity['Publisher'],
          '', 'Пересборка из C:\\Users\\acer\\Documents\\Full:',
          'powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\\tools\\build-msix.ps1',
          '', 'Физическая печать и отправка пакета в Store не выполнялись. WACK не запускался. Реальный жест мышью для этой оптимизации не использовался: измерялись обработчики кнопок в Tk и контрольный таймер основного цикла.',
          '', 'Подробные измерения и отчёты: verification-'+VERSION+'.json; журналы и изображения: dist/verification-'+VERSION+'.']
report=root/f'dist/store/Проверка-{VERSION}.txt'
report.write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(target)
print(report)
