"""Presentation-only language/units. Model keys and geometry remain unchanged."""
import json
import os
from pathlib import Path
import re
import tkinter as tk
from tkinter import ttk, filedialog as native_files, messagebox as native_messages


EN = {
    '↔ Отразить':'↔ Mirror', '↕ Отразить':'↕ Flip',
    'Поменять местами левую и правую стороны':'Swap left and right sides',
    'Поменять местами верх и низ':'Swap top and bottom sides',
    'Подготовка документов…':'Preparing documents…',
    'Предупреждения импорта':'Import warnings',
    'Связать пропорции':'Link proportions','Разблокировать пропорции':'Unlock proportions',
    'Связать вылеты':'Link bleed','Разблокировать вылеты':'Unlink bleed',
    'Яркость':'Brightness', 'Гамма':'Gamma',
    'Метки и линии':'Marks and lines','Отступ меток внутрь':'Mark inset','Отступ линий внутрь':'Line inset',
    'метки':'marks','линии':'lines',
    'Вспомогательный контур касается чистового реза или находится внутри изделия. Часть штриха может остаться после резки. Уменьшите отступ линий.':
        'The helper contour touches the finished cut or lies inside the product. Part of the stroke may remain after cutting. Reduce the line inset.',
    'Связать вылеты: следующее изменение применяется ко всем сторонам':'Link bleed: the next edit applies to every side',
    'Пусто':'Blank', 'Задняя':'Back', 'Назад':'Back', 'Далее':'Next',
    'листов':'sheets', 'листа':'sheets', 'лист':'sheet', 'стороны':'sides', 'сторон':'sides',
    'Подготовка предпросмотра…':'Preparing preview…',
    'Не удалось подготовить предпросмотр: ':'Could not prepare preview: ',
    'Выберите фото слева и назначьте панель':'Select a photo on the left and assign a panel',
    'Линия по центру':'Center line', 'Вертикальная':'Vertical', 'Горизонтальная':'Horizontal',
    'Метки сгиба':'Fold marks', 'Риски по краям':'Edge ticks', 'Сплошная линия':'Solid line',
    'Сторона':'Side', 'Лицевая сторона':'Front cover', 'Задняя сторона':'Back cover',
    'Внутри слева':'Inside left', 'Внутри справа':'Inside right', 'Лицевая':'Front', 'Оборот':'Back', 'Обе':'Both',
    'Открытка со сгибом':'Folded postcard', 'Буклет':'Booklet', 'Снаружи':'Outside', 'Внутри':'Inside',
    'Добавлено пустых страниц':'Added blank pages',
    '+ Пустая страница':'+ Blank page', 'Пустая страница':'Blank page',
    'Пустые страницы':'Blank pages', 'Изменить…':'Edit…', 'Вставить по номеру…':'Insert by number…',
    'Номера…':'Numbers…', 'Вставить…':'Insert…',
    'Дублировать':'Duplicate', 'Заполнить страницу':'Fill page',
    'Добавлена для сгиба':'Added for folding', 'Добавлено для сгиба':'Added for folding',
    'Перетащите сюда фото':'Drop a photo here', 'Страница ':'Page ',
    'Номера пустых страниц в порядке чтения':'Blank page numbers in reading order',
    'Например: 0, 1, 4-6, END. Фотографии сохранят свой порядок.':'For example: 0, 1, 4-6, END. Photos keep their order.',
    'Страниц:':'Pages:', 'Сторон:':'Sides:', 'Применить':'Apply',
    'Вставить пустые страницы':'Insert blank pages', 'Страница № (0, 1… или END)':'Page number (0, 1… or END)',
    'Перед':'Before', 'Количество':'Quantity',
    'Укажите номера: 0, 1, 4-6, END.':'Enter page numbers: 0, 1, 4-6, END.',
    'Неверный диапазон страниц.':'Invalid page range.', 'Неверный номер страницы.':'Invalid page number.',
    'Неверное количество страниц.':'Invalid page count.',
    'Пустую обложку сначала заполните фотографией или укажите 0 / END.':'Fill the empty cover with a photo first, or include 0 / END.',
    'Вставляйте внутренние страницы между 0 и END.':'Insert internal pages between 0 and END.',
    'Добавьте фото или создайте дубликат и перетащите его на пустую страницу.':'Add a photo or create a duplicate and drag it onto the blank page.',
    'Пустых страниц':'Blank pages', 'Очистить страницу':'Clear page', 'Удалить страницу':'Delete page',
    'В свойствах принтера включите двустороннюю печать с переворотом по короткому краю. ':
        'Enable duplex printing with short-edge binding in printer properties. ',
    "без правок":"no adjustments",
    "Будут сброшены: раскладка, поля, зазор, выравнивание, подрезка, кадрирование и цвет. Фото, количество копий, язык и единицы сохранятся.":
        "Reset layout, margins, gap, alignment, trimming, cropping and color. Photos, copy counts, language and units will be kept.",
    'Размещение': 'Placement', 'есть коррекция': 'correction active', 'без коррекции': 'no correction',
    'метки': 'marks', 'линии': 'lines', 'нет': 'none', 'внутрь': 'inward',
    '↺ Сбросить настройки…': '↺ Reset settings…', 'Сбросить настройки?': 'Reset settings?',
    'Сбросить раскладку, кадрирование и цвет? Фото и число копий сохранятся.':
        'Reset layout, cropping and color? Photos and copy counts will be kept.',
    'Выбрано: ':'Selected: ', 'Разные значения':'Mixed values', 'Для выбранных фото':'For selected photos',
    'Кадрирование':'Cropping','Поворот':'Rotation','Масштаб':'Zoom','Кривая RGB':'RGB curve',
    'Фото и документы':'Photos and documents', 'Все файлы':'All files', 'Добавить':'Add',
    'Взять размер страницы из PDF':'Use PDF page size', 'Импорт PDF':'Import PDF',
    'PDF в этой папке':'PDFs in this folder', 'Все страницы':'All pages',
    'Диапазон страниц':'Page range', 'Только первые страницы':'First pages only', 'Пропустить PDF':'Skip PDFs',
    ' · стр. ':' · page ', 'например ':'for example ',
    'В папке нет поддерживаемых фото или документов. Подпапки не просматриваются.':'No supported photos or documents in this folder. Subfolders are not searched.',
    'Неподдерживаемый формат файла':'Unsupported file format',
    'PDF не читается или требует пароль: ':'PDF cannot be read or requires a password: ',
    'Неверный диапазон страниц. Допустимы страницы ':'Invalid page range. Available pages: ',
    'Выберите хотя бы одну страницу.':'Select at least one page.',
    'Сохраните PSD в Photoshop с включённой максимальной совместимостью или экспортируйте в PNG/TIFF':
        'Save the PSD in Photoshop with Maximize Compatibility enabled, or export to PNG/TIFF',
    'Перетащите фото или папку сюда': 'Drop photos or a folder here',
    'Добавлено ': 'Photos added: ', ' фото, пропущено ': '; skipped: ', ' файлов': ' files',
    'Края макета могут быть обрезаны': 'Layout edges may be clipped',
    'Не удалось открыть принтер: ': 'Could not open printer: ',
    'Не удалось создать контекст печати: ': 'Could not create the print context: ',
    'Не удалось создать задание печати: ': 'Could not create the print job: ',
    'Физический формат бумаги драйвера не удалось подтвердить.': 'The physical driver paper size could not be confirmed.',
    'Формат бумаги драйвера не подтверждён': 'Driver paper size is unconfirmed',
    'Вернуться в свойства': 'Return to properties',
    'Печатать с настройками драйвера': 'Print with driver settings',
    'Печать с настройками текущего задания драйвера: масштаб 100%, без подгонки.': 'Print with the current driver job settings: 100% scale, no fitting.',
    'Бумага меньше макета: края изображения могут быть обрезаны.': 'Paper is smaller than the layout: image edges may be clipped.',
    'Размер бумаги неизвестен: возможна обрезка краёв.': 'Paper size is unknown: edges may be clipped.',
    'Сохранение PDF': 'Saving PDF', 'Повторить': 'Retry', 'Сохранить под другим именем': 'Save as',
    'Не удалось заменить PDF. Возможно, он открыт в другой программе или папка недоступна для записи':
        'Could not replace the PDF. It may be open in another application, or the folder may not be writable',
    "Оттиск Фото": "Ottisk Photo", "Русский": "Русский",
    "Разделить лист": "Divide sheet", "Задать размер фото": "Set photo size", "Фото с рамкой": "Framed photo",
    "Раскладка": "Layout", "Бумага": "Paper", "Ориентация": "Orientation", "Книжная": "Portrait", "Альбомная": "Landscape",
    "Книжная / Альбомная": "Portrait / Landscape", "книжная": "portrait", "альбомная": "landscape",
    "Свой размер": "Custom size", "Свой шаблон": "Custom template", "Размер фото": "Photo size",
    "Шаблон карточки": "Card template", "Карточка, Ш × В": "Card, W × H", "Окно, Ш × В": "Window, W × H",
    "Отступ сверху / слева": "Top / left offset", "Исходный размер": "Original size",
    "Поля листа": "Sheet margins", "Зазор": "Gap", "Фото на листе": "Photos per sheet",
    "Сохранять позиции на всех листах": "Keep positions on all sheets", "Авто": "Auto", "Рядом": "Side by side", "Стопкой": "Stacked",
    "Слева": "Left", "Справа": "Right", "Сверху": "Top", "Снизу": "Bottom",
    "По центру горизонтали": "Centre horizontally", "По центру вертикали": "Centre vertically",
    "Выбранное фото": "Selected photo", "Обрезать до краёв": "Crop to edges", "Фото целиком": "Fit entire photo",
    "Сбросить кадр": "Reset crop", "Увеличить фото": "Enlarge photo", "Уменьшить фото до 100%": "Reduce photo to 100%",
    "Применить кадрирование ко всем": "Apply crop mode to all", "Лист по размеру карточки": "Sheet to card size",
    "Вписать лист": "Fit sheet", "Цвет": "Colour", "Для всех фото": "For all photos", "Для выбранного фото": "For selected photo",
    "Индивидуально для выбранного фото": "Individual for selected photo", "Сочность": "Vibrance",
    "Температура": "Temperature", "Оттенок": "Tint", "холоднее ↔ теплее": "cooler ↔ warmer", "зелёный ↔ пурпурный": "green ↔ magenta",
    "Кривые RGB…": "RGB curves…", "Кривые RGB": "RGB curves", "До": "Before", "После": "After",
    "Дополнительно…": "Advanced…", "Дополнительные настройки": "Advanced settings", "Сбросить цвет": "Reset colour",
    "Сбросить кривую": "Reset curve", "Готово": "Done", "Двойной щелчок: 1,00": "Double click: 1.00",
    "ЛКМ: добавить/двигать · ПКМ или Delete: удалить": "Left: add/move · Right or Delete: remove",
    "Подрезка": "Trimming", "Метки реза": "Cut marks", "Рез": "Cut", "Нет": "None", "Линии": "Lines", "Метки": "Marks",
    "Исходный размер при ": "Original size at ",
    "Отступ реза внутрь, мм": "Cut inset, mm", "После реза:": "After cutting:",
    "＋  Добавить фото": "＋  Add photos", "Добавить фото": "Add photos", "Добавить фотографии": "Add photos",
    "Открыть папку": "Open folder", "Открыть папку с фотографиями": "Open photo folder", "Фотографии": "Photos",
    "Добавьте фотографии\nили выберите папку": "Add photos\nor choose a folder", "Удалить": "Remove", "Копий": "Copies",
    "Своя кривая": "Own curve", "Предпросмотр печати": "Print preview", "Ваши фотографии\nпоявятся здесь": "Your photos\nwill appear here",
    "ДО · без коррекции": "BEFORE · no correction", "Выберите снимок слева или на листе": "Select a photo in the list or on the sheet",
    "Печать…": "Print…", "Печать —": "Print —", "Сохранить PDF": "Save PDF", "Документ PDF": "PDF document",
    "Принтер": "Printer", "Разрешение вывода": "Output resolution", "Объём печати": "Print range", "Управление цветом": "Colour management",
    "Все листы": "All sheets", "Текущий лист": "Current sheet", "Цветом управляет принтер": "Printer manages colour",
    "Цветом управляет Оттиск Фото": "Ottisk Photo manages colour", "Свойства принтера…": "Printer properties…",
    "Выбрать ICC из файла…": "Choose ICC file…", "Выбрать выходной ICC": "Choose output ICC", "Цветовые профили": "Colour profiles",
    "Отмена": "Cancel", "Печатать": "Print", "Закрыть": "Close", "Подготовка листов…": "Preparing sheets…",
    "Подготовка листа": "Preparing sheet", " из ": " of ", "Отправлено в очередь печати": "Sent to print queue",
    " · задание ": " · job ", "Передача в очередь Windows…": "Sending to the Windows queue…",
    "Печать отменена. Задание не создано.": "Printing cancelled. No job was created.",
    "Отмена подготовки… Задание не будет создано.": "Cancelling preparation… No job will be created.",
    "Передача задания Windows уже началась. Дождитесь результата.": "Sending to Windows has begun. Please wait for the result.",
    "Ошибка прямой печати": "Direct printing error", "Автоматическая повторная отправка не выполняется.": "The job will not be retried automatically.",
    "В Windows нет доступных принтеров. Установите драйвер и откройте диалог заново.": "No Windows printers are available. Install a driver and reopen this dialog.",
    "Принтер не выбран": "No printer selected", "текущий лист ": "current sheet ", "все листы: ": "all sheets: ",
    " отпечатков": " prints", "Отпечатков:": "Prints:", "Листов:": "Sheets:", "Лист ": "Sheet ",
    "Занято ": "Occupied ", " мест": " slots", "До ": "Up to ", " фото на листе": " photos per sheet", " карточек на листе": " cards per sheet",
    "Карточка ": "Card ", "Окно ": "Window ", "Сверху ": "Top ", "Слева ": "Left ", "Размер фото ": "Photo size ",
    "Выбранное фото:": "Selected photo:", " ppi после кадрирования — ниже ": " ppi after cropping — below ",
    "Увеличение растра не добавляет деталей.": "Upsampling does not add detail.",
    "JPG, JPEG и PNG · исходники остаются без изменений": "JPG, JPEG and PNG · originals remain unchanged",
    "Добавлено:": "Added:", "Всего фотографий:": "Total photos:", "Создание PDF из исходных фотографий…": "Creating PDF from original photos…",
    "Сохранено листов:": "Sheets saved:", "Не удалось сохранить PDF.": "Could not save PDF.", "Ошибка экспорта PDF": "PDF export error",
    "Не удалось открыть папку": "Could not open folder", "Фотографии не найдены": "No photos found",
    "В папке нет JPG, JPEG или PNG. Подпапки не просматриваются.": "No JPG, JPEG or PNG files in this folder. Subfolders are not scanned.",
    "Некоторые фото не добавлены": "Some photos were not added", "поддерживаются JPG, JPEG и PNG": "supported formats: JPG, JPEG and PNG",
    "Проверьте шаблон карточки": "Check card template", "Проверьте параметры карточки / реза": "Check card / cut settings",
    "Размер фото не помещается / проверьте размеры": "Photo does not fit / check dimensions",
    "Вывод заблокирован до исправления параметров": "Output blocked until settings are corrected",
    "Размеры карточки и окна должны быть от 1 до 2000 мм.": "Card and window dimensions must be between 1 and 2000 mm.",
    "Отступы окна должны быть неотрицательными.": "Window offsets must be non-negative.",
    "Окно выходит за пределы карточки. Уменьшите окно или отступы сверху и слева.": "The window extends beyond the card. Reduce the window or its top/left offsets.",
    "Количество копий должно быть целым числом не меньше 1.": "Copies must be an integer of at least 1.",
    "Сочность должна быть от −100 до +100.": "Vibrance must be between −100 and +100.",
    "Температура и оттенок должны быть от −100 до +100.": "Temperature and tint must be between −100 and +100.",
    "Gamma должна быть от 0,50 до 2,00.": "Gamma must be between 0.50 and 2.00.",
    "Размеры должны быть от 1 до 2000 мм.": "Dimensions must be between 1 and 2000 mm.",
    "Поля и промежуток должны быть неотрицательными.": "Margins and gap must be non-negative.",
    "Некорректные непечатаемые поля принтера.": "Invalid printer non-printable margins.",
    "Неизвестная раскладка.": "Unknown layout.", "Раскладка карточек должна использовать их внешний размер.": "Card layout must use the outer card dimensions.",
    "Неизвестный режим подрезки.": "Unknown trimming mode.", "Отступ реза внутрь должен быть неотрицательным.": "Cut inset must be non-negative.",
    "После реза размер неположительный. Уменьшите отступ реза внутрь.": "The cut size is not positive. Reduce the cut inset.",
    "Неизвестное выравнивание или вариант размещения.": "Unknown alignment or placement.",
    "Укажите целое число фото на листе.": "Enter an integer number of photos per sheet.",
    "Для ячеек выберите 1, 2, 4, 6 или 9 фото.": "Choose 1, 2, 4, 6 or 9 photos for cells.",
    " не помещается даже с поворотом. ": " does not fit, even when rotated. ", "Доступная область:": "Available area:",
    "Выберите бумагу больше или уменьшите размер фото.": "Choose larger paper or reduce the photo size.",
    "Поля и промежутки занимают всю рабочую область листа.": "Margins and gaps use the entire working area.",
    "Полный комплект меток реза не помещается вне готовых отпечатков.": "The full set of cut marks does not fit outside the finished prints.",
    "Увеличьте поля листа или зазор; размеры и раскладка не изменены.": "Increase sheet margins or gap; dimensions and layout have not changed.",
    "Удлинённые метки не помещаются. Увеличьте поля листа или зазор.": "Extended marks do not fit. Increase sheet margins or gap.",
    "Удлинённые метки задевают соседний отпечаток. Увеличьте поля листа или зазор.": "Extended marks overlap another print. Increase sheet margins or gap.",
    "Разрешение вывода должно быть 300 или 600 ppi.": "Output resolution must be 300 or 600 ppi.",
    "Сначала добавьте фотографии.": "Add photos first.", "Нельзя перезаписать исходную фотографию.": "An original photo cannot be overwritten.",
    "Введите числовые размеры, поля и промежуток в миллиметрах.": "Enter numeric dimensions, margins and gap.",
    "Введите числовые размеры, поля и промежуток.": "Enter numeric dimensions, margins and gap.",
    "Поля и зазор. Стрелки: 1 мм / 0,01 in, дробные значения можно вводить вручную.": "Margins and gap. Arrows: 1 mm / 0.01 in; fractional values may be entered manually.",
    "Выберите число фото на листе.": "Choose photos per sheet.",
    "Укажите число копий не меньше 1. Для исключения фото используйте «Удалить».": "Enter at least 1 copy. Use Remove to exclude a photo.",
    "Добавьте фото. Без метаданных используется 300 ppi.": "Add a photo. Without metadata, 300 ppi is used.",
    "при отсутствии пригодного PPI": "if valid PPI is unavailable", "PPI не найден/непригоден": "PPI missing/invalid", "из метаданных": "from metadata",
    "Замок: при изменении стороны сохранять пропорции выбранного снимка": "Lock: preserve the selected photo's proportions when editing either side",
    "Поля и зазор в миллиметрах. Стрелки: шаг 1 мм, дробные значения можно вводить вручную.": "Margins and gap. Arrow step: 1 mm; fractional values can be entered manually.",
    "300 / 600 ppi: плотность растра PDF и прямой печати. Размеры в мм сохраняются.": "300 / 600 ppi: raster density for PDF and direct printing. Physical dimensions are preserved.",
    "Поля 0 мм: драйвер может обрезать край, а «Без полей» может увеличить изображение. ": "Zero margins: the driver may clip edges; Borderless may enlarge the image. ",
    "Для точных размеров отключите «Без полей». ": "Disable Borderless for exact sizes. ",
    "Приложение печатает в масштабе 100%; драйвер может обрезать края листа.\n": "The app prints at 100%; the driver may clip sheet edges.\n",
    "«Без полей», внутреннее увеличение и цветокоррекцию драйвера проверить нельзя — задайте их вручную в свойствах.": "Borderless, driver enlargement and driver colour correction cannot be verified; set them manually in Properties.",
    " · вручную отключите цветокоррекцию в свойствах драйвера.": " · manually disable colour correction in driver properties.",
    "Выберите пригодный RGB ICC заново.": "Choose a valid RGB ICC profile again.",
    "Текущий лист недоступен.": "Current sheet is unavailable.", "Выберите 300 или 600 ppi.": "Choose 300 or 600 ppi.", "В заказе нет листов.": "The order has no sheets.",
    "мм": "mm", "см": "cm",
    "Макет:": "Layout:", "Драйвер:": "Driver:", "масштаб ": "scale ", "%, копий ": "%, copies ",
    "Вернитесь в «Свойства принтера…»: нужен формат макета, масштаб 100% и одна копия. Макет не подгоняется.":
        "Return to Printer properties: use the layout paper size, 100% scale and one copy. The layout will not be fitted.",
    "Драйвер не вернул параметры DEVMODE.": "The driver did not return DEVMODE settings.",
    "Драйвер отклонил параметры бумаги (код ": "The driver rejected the paper settings (code ",
    "Не удалось открыть свойства драйвера (код ": "Could not open driver properties (code ",
    "Windows не разрешила задать режим управления цветом. Задание не создано.": "Windows did not accept the colour management mode. No job was created.",
    "Встроенный ICC не читается или несовместим: ": "The embedded ICC is unreadable or incompatible: ",
    ". Фото не импортировано.": ". The photo was not imported.",
    "Несовместимый или недоступный выходной ICC: ": "Incompatible or unavailable output ICC: ",
    "для вывода GDI нужен обычный RGB ICC; CMYK, Lab и DeviceLink не поддерживаются": "GDI output requires a regular RGB ICC; CMYK, Lab and DeviceLink are not supported",
    "Точки кривой должны идти слева направо от 0 до 255.": "Curve points must run left to right from 0 to 255.",
}


EN.update({
    'Драйвер не заявляет автоматическую двустороннюю печать. Проверьте ручной переворот в свойствах драйвера; для явной отправки используйте «Печатать с настройками драйвера».':'The driver does not report automatic duplex support. Check manual flipping in its properties; use Print with driver settings to send explicitly.',
    'В свойствах принтера включите двустороннюю печать с переворотом по длинному краю. ':'In printer properties, enable two-sided printing and flip on the long edge. ',
    'Точный размер · N-Up':'Exact size · N-Up','Тираж · Step & Repeat':'Run · Step & Repeat',
    'Управление форматами…':'Manage paper sizes…','Управление форматами':'Manage paper sizes',
    'Лицо':'Front','Оборот':'Back','Двусторонний тираж':'Two-sided run','Пустой оборот':'Blank back',
    'Переворот':'Flip edge','Длинный край':'Long edge','Короткий край':'Short edge',
    'короткий край':'short edge','длинный край':'long edge','короткому':'short','длинному':'long',
    'Размер изделия после реза':'Finished product size','Заполнить один лист':'Fill one sheet',
    'Задать тираж':'Set quantity','Готовых изделий':'Finished products','Замок':'Lock ratio',
    'Тираж':'Run','Размер страницы':'Page size','По размеру листа':'Fit sheet',
    'Точный размер страницы':'Exact page size','После реза':'After trimming',
    'Экземпляров на листе':'Copies per sheet','Вылеты':'Bleed',
    'Зазор — между внешними границами вылетов':'Gap is measured between outside bleed edges',
    'Пользовательский лист':'Custom paper','Название':'Name','Ширина':'Width','Высота':'Height',
    'Создать':'Create','Дублировать':'Duplicate','Сохранить':'Save','Сохранено.':'Saved.',
    'Встроенный формат можно дублировать.':'Built-in sizes can be duplicated.',
    'Встроенный формат можно только дублировать.':'Built-in sizes can only be duplicated.',
    'Встроенный формат нельзя удалить.':'Built-in sizes cannot be deleted.',
    'Введите название формата.':'Enter a paper name.',
    'Размеры листа должны быть от 1 до 2000 мм — предел текущего пути вывода.':'Paper dimensions must be 1–2000 mm, the output path limit.',
    'Назначьте источник лица.':'Assign a front source.',
    'Тираж должен быть целым положительным числом.':'Quantity must be a positive integer.',
    'Разворот':'Spread','доступно':'available','Сетка':'Grid','вместимость':'capacity',
    'изделий':'products','экземпляров на стороне':'copies per side','Последний лист':'Last sheet',
    'Не хватает вылета':'Insufficient bleed','не хватает вылета':'insufficient bleed',
    'Растр заполняет область вылета; размер после реза сохранён.':'Raster fills the bleed area; finished size is preserved.',
    'Цветокоррекция требует растрового вывода этой страницы PDF.':'Colour correction requires raster output for this PDF page.',
    'Формы или аннотации этой страницы PDF требуют растрового вывода.':'Forms or annotations require raster output for this PDF page.',
    'Растровый вывод отдельных страниц PDF':'Raster output for selected PDF pages',
    'Продолжить сохранение?':'Continue saving?',
})


def preferences_path():
    return Path(os.environ.get("OTTISK_PHOTO_PREFERENCES", str(Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "OttiskPhoto" / "preferences.json")))


def load_preferences():
    try:
        data = json.loads(preferences_path().read_text(encoding="utf-8"))
        result = {"language": "en" if data.get("language") == "en" else "ru", "units": "in" if data.get("units") == "in" else "mm"}
        count = str(data.get('photos_per_sheet',data.get('count','1')))
        result['photos_per_sheet'] = count if count in ('1','2','4','6','9') else '1'
        return result
    except (OSError, ValueError, TypeError):
        return {"language": "ru", "units": "mm", 'photos_per_sheet':'1'}


def save_preferences(language, units, photos_per_sheet=None):
    path = preferences_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data,dict): data = {}
    except (OSError,ValueError):
        data = {}
    data.update(language=language,units=units)
    if str(photos_per_sheet) in ('1','2','4','6','9'):
        data['photos_per_sheet'] = str(photos_per_sheet)
    temporary.write_text(json.dumps(data), encoding="utf-8")
    temporary.replace(path)


def translate(text, language="ru", units="mm"):
    text = str(text)
    if language == "en":
        text = re.sub(r'^Выбрано: (\d+) фото$',r'Selected: \1 photos',text)
        # One substitution pass prevents a shorter key from re-translating
        # fragments of an already translated long phrase.
        text = re.sub("|".join(re.escape(k) for k in sorted(EN, key=len, reverse=True)), lambda m: EN[m[0]], text)
    if units == "in" and not (" / " in text and " in" in text):
        text = re.sub(r"(от|between) (\d+(?:[.,]\d+)?) (до|and) (\d+(?:[.,]\d+)?) (мм|mm)",
                      lambda m: f"{m[1]} {float(m[2].replace(',', '.'))/25.4:.6g} {m[3]} {float(m[4].replace(',', '.'))/25.4:.6g} in", text)
        def inches(match):
            values = re.findall(r"\d+(?:[.,]\d+)?", match[1])
            return " × ".join(f"{float(v.replace(',', '.')) / 25.4:.6g}" for v in values) + " in"
        text = re.sub(r"(\d+(?:[.,]\d+)?(?:\s*×\s*\d+(?:[.,]\d+)?)?)\s*(?:мм|mm)\b", inches, text)
        text = text.replace("мм", "in").replace(", mm", ", in")
        if text == "mm":
            text = "in"
    return text


def ui_text(widget, text):
    root = widget._root()
    return getattr(root, "_translate", lambda value: str(value))(text)


def localize_tree(widget, _key=None):
    """Translate presentation widgets, never the StringVars used as model keys."""
    from .widgets import CapsuleButton
    if _key is None:
        _key=(ui_text(widget,'Сохранить PDF'),ui_text(widget,'мм'))
    changed=getattr(widget,'_localized_key',None)!=_key
    if changed and isinstance(widget, (tk.Tk, tk.Toplevel)):
        if not hasattr(widget, "_source_title"):
            widget._source_title = widget.title()
        widget.title(ui_text(widget, widget._source_title))
    if isinstance(widget, CapsuleButton):
        if changed:
            if hasattr(widget, "_sync"):
                widget._sync()
            else:
                widget.redraw()
    elif isinstance(widget, (tk.Label, ttk.Label, ttk.LabelFrame, ttk.Checkbutton)) and not getattr(widget, "_l10n_skip", False):
        variable = str(widget.cget("textvariable")) if "textvariable" in widget.keys() else ""
        if variable and not hasattr(widget, "_display_variable"):
            widget._display_variable = tk.StringVar(master=widget)
            def update(*_):
                try:
                    widget._display_variable.set(ui_text(widget, widget.getvar(variable)))
                except tk.TclError:
                    pass
            command = widget.register(update)
            widget.tk.call("trace", "add", "variable", variable, "write", command)
            def cleanup(event):
                if event.widget == widget:
                    try:
                        widget.tk.call("trace", "remove", "variable", variable, "write", command)
                        widget.deletecommand(command)
                    except tk.TclError:
                        pass
            widget.bind("<Destroy>", cleanup, add=True)
            widget._update_translation = update
            widget.configure(textvariable=widget._display_variable)
        if hasattr(widget, "_update_translation"):
            if changed:widget._update_translation()
        elif "text" in widget.keys():
            current = str(widget.cget("text"))
            if not hasattr(widget, "_source_label") or current != widget._last_translation:
                widget._source_label = current
                changed=True
            if changed:
                widget._last_translation = ui_text(widget, widget._source_label)
                widget.configure(text=widget._last_translation)
    widget._localized_key=_key
    for child in widget.winfo_children():
        localize_tree(child,_key)


class Dialogs:
    def __init__(self, module):
        self.module = module

    def __getattr__(self, name):
        function = getattr(self.module, name)
        def call(*args, **kwargs):
            parent = kwargs.get("parent") or tk._default_root
            tr = lambda value: ui_text(parent, value) if parent else str(value)
            args = tuple(tr(a) if isinstance(a, str) else a for a in args)
            for key in ("title", "message", "detail", "initialfile"):
                if key in kwargs:
                    kwargs[key] = tr(kwargs[key])
            if "filetypes" in kwargs:
                kwargs["filetypes"] = [(tr(label), pattern) for label, pattern in kwargs["filetypes"]]
            return function(*args, **kwargs)
        return call


filedialog, messagebox = Dialogs(native_files), Dialogs(native_messages)
