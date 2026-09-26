from __future__ import annotations

import os
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from typing import TextIO


SUPPORTED_LANGUAGES = ("fr", "en", "ru", "zh")
LANGUAGE_NAMES = {
    "fr": "Français",
    "en": "English",
    "ru": "Русский",
    "zh": "中文",
}


BRAND_WIDTH = 52
BRAND_HEIGHT = 11
BRAND_FRAME_DELAY = 0.045
COMET = ("     ╱", "━━━━◆", "     ╲")


def _brand_frame(x: int, y: int, spark: str = " ", lit: bool = False) -> tuple[str, ...]:
    """Compose une image fixe sans séquences ANSI, donc testable et portable."""
    canvas = [[" "] * BRAND_WIDTH for _ in range(BRAND_HEIGHT)]

    def overlay(left: int, top: int, lines: tuple[str, ...]) -> None:
        for row_offset, line in enumerate(lines):
            row = top + row_offset
            if not 0 <= row < BRAND_HEIGHT:
                continue
            for column_offset, character in enumerate(line):
                column = left + column_offset
                if character != " " and 0 <= column < BRAND_WIDTH:
                    canvas[row][column] = character

    overlay(x, y, COMET)
    overlay(31, 4, (spark,))
    overlay(29, 5, ("\\ | /",))
    overlay(24, 6, ("━━━━━━\\|/━━━━━━",))
    overlay(22, 7, (
        "┏━━━━━━━━━━━━━━━━━┓",
        "┃    KomaForge    ┃" if lit else "┃                 ┃",
        "┗━━━━━━┳━━━┳━━━━━━┛",
        "    ━━━┻━━━┻━━━",
    ))
    return tuple("".join(row).rstrip() for row in canvas)


# Le personnage traverse l'écran, allume la forge, puis laisse une image finale
# propre. L'animation entière dure 180 ms dans un vrai terminal uniquement.
BRAND_FRAMES = (
    _brand_frame(1, 0),
    _brand_frame(9, 0, "."),
    _brand_frame(17, 1, "."),
    _brand_frame(25, 1, "o"),
    _brand_frame(27, 0, "*", lit=True),
)
BRAND_ART = BRAND_FRAMES[-1]

BRAND_ART_COLORS = (
    "1;33", "1;33", "1;33", "2;33",  # comète et trajectoire
    "1;93", "1;31", "1;33",  # étincelle et impact
    "1;37", "1;36", "1;37", "2;37",  # enclume et signature
)


MESSAGES: dict[str, dict[str, str]] = {
    "fr": {
        "tagline": "Transformez une publication web en archive propre et lisible.",
        "authorization": "Utilisez uniquement des contenus que vous possédez ou pouvez archiver.",
        "language_title": "Langue / Language / Язык / 语言",
        "language_prompt": "Langue",
        "language_invalid": "Choisissez 1, 2, 3 ou 4.",
        "menu_title": "Que souhaitez-vous faire ?",
        "menu_auto": "Extraction guidée",
        "menu_auto_hint": "Détection automatique, réglages essentiels seulement",
        "menu_advanced": "Options avancées",
        "menu_advanced_hint": "Sélecteurs, portée, filigranes et diagnostics",
        "menu_quit": "Quitter",
        "choice": "Choix",
        "invalid_choice": "Choix invalide. Utilisez 1, 2 ou 3.",
        "source_title": "Source",
        "url_prompt": "URL de la publication",
        "url_missing": "Aucune URL fournie.",
        "output_title": "Sortie",
        "output_prompt": "Dossier racine",
        "format_title": "Format final",
        "format_original": "Original",
        "format_original_hint": "PDF/EPUB natif, sinon CBZ avec les images originales",
        "format_cbz_hint": "Archive ZIP pour manga, BD et pages image",
        "format_cbr_hint": "Archive RAR; nécessite WinRAR ou rar",
        "format_pdf_hint": "Document original ou PDF fixe construit depuis les pages",
        "format_epub_hint": "Livre original ou EPUB fixe construit depuis les pages",
        "format_images_hint": "Fichiers originaux conservés dans un dossier",
        "format_prompt": "Format",
        "format_invalid": "Format invalide. Utilisez un nombre de 1 à 6.",
        "manual_login": "Le site exige-t-il une connexion manuelle ?",
        "advanced_title": "Réglages avancés",
        "scope_prompt": "Portée (auto, document ou work)",
        "scope_invalid": "Portée invalide : auto, document ou work uniquement.",
        "selector_prompt": "Sélecteur CSS des pages",
        "expected_prompt": "Nombre de pages attendu",
        "expected_invalid": "Le nombre de pages doit être un entier positif.",
        "reading_selector_prompt": "Sélecteur du mode lecture",
        "reading_value_prompt": "Valeur du mode lecture",
        "watermark_prompt": "Filigranes SVG (remove ou detect)",
        "watermark_invalid": "Choisissez remove ou detect.",
        "watermark_text_prompt": "Texte exact supplémentaire à retirer",
        "summary_title": "Prêt à démarrer",
        "label_url": "URL",
        "label_output": "Sortie",
        "label_format": "Format",
        "label_mode": "Mode",
        "auto_title_placeholder": "<titre détecté>",
        "inspect_mode": "inspection uniquement; aucun téléchargement",
        "cancelled": "Opération annulée.",
        "error": "ERREUR",
        "missing_url_cli": "URL manquante. Ajoutez une URL ou lancez le menu interactif.",
        "invalid_url": "L’URL doit commencer par http:// ou https://",
        "markdown_mismatch": "Le texte et la cible du lien Markdown diffèrent. Collez directement l’URL voulue.",
        "pdf_conflict": "Utilisez soit --pdf, soit --format, pas les deux.",
    },
    "en": {
        "tagline": "Turn a web publication into a clean, readable archive.",
        "authorization": "Only use content you own or are allowed to archive.",
        "language_title": "Language / Langue / Язык / 语言",
        "language_prompt": "Language",
        "language_invalid": "Choose 1, 2, 3, or 4.",
        "menu_title": "What would you like to do?",
        "menu_auto": "Guided extraction",
        "menu_auto_hint": "Automatic detection with only essential settings",
        "menu_advanced": "Advanced options",
        "menu_advanced_hint": "Selectors, scope, watermarks, and diagnostics",
        "menu_quit": "Quit",
        "choice": "Choice",
        "invalid_choice": "Invalid choice. Use 1, 2, or 3.",
        "source_title": "Source",
        "url_prompt": "Publication URL",
        "url_missing": "No URL was provided.",
        "output_title": "Output",
        "output_prompt": "Root folder",
        "format_title": "Final format",
        "format_original": "Original",
        "format_original_hint": "Native PDF/EPUB, otherwise CBZ with original images",
        "format_cbz_hint": "ZIP archive for manga, comics, and image pages",
        "format_cbr_hint": "RAR archive; requires WinRAR or rar",
        "format_pdf_hint": "Original document or fixed-layout PDF built from pages",
        "format_epub_hint": "Original book or fixed-layout EPUB built from pages",
        "format_images_hint": "Original files kept in a folder",
        "format_prompt": "Format",
        "format_invalid": "Invalid format. Use a number from 1 to 6.",
        "manual_login": "Does the site require a manual sign-in?",
        "advanced_title": "Advanced settings",
        "scope_prompt": "Scope (auto, document, or work)",
        "scope_invalid": "Invalid scope: use auto, document, or work.",
        "selector_prompt": "Page CSS selector",
        "expected_prompt": "Expected page count",
        "expected_invalid": "The page count must be a positive integer.",
        "reading_selector_prompt": "Reading-mode selector",
        "reading_value_prompt": "Reading-mode value",
        "watermark_prompt": "SVG watermarks (remove or detect)",
        "watermark_invalid": "Choose remove or detect.",
        "watermark_text_prompt": "Additional exact text to remove",
        "summary_title": "Ready to start",
        "label_url": "URL",
        "label_output": "Output",
        "label_format": "Format",
        "label_mode": "Mode",
        "auto_title_placeholder": "<detected title>",
        "inspect_mode": "inspection only; nothing will be downloaded",
        "cancelled": "Operation cancelled.",
        "error": "ERROR",
        "missing_url_cli": "Missing URL. Add a URL or start the interactive menu.",
        "invalid_url": "The URL must start with http:// or https://",
        "markdown_mismatch": "The Markdown label and target differ. Paste the intended URL directly.",
        "pdf_conflict": "Use either --pdf or --format, not both.",
    },
    "ru": {
        "tagline": "Превратите веб-публикацию в аккуратный и удобный архив.",
        "authorization": "Используйте только материалы, которые вам принадлежат или разрешены к архивированию.",
        "language_title": "Язык / Language / Langue / 语言",
        "language_prompt": "Язык",
        "language_invalid": "Выберите 1, 2, 3 или 4.",
        "menu_title": "Что вы хотите сделать?",
        "menu_auto": "Пошаговое извлечение",
        "menu_auto_hint": "Автоопределение и только основные настройки",
        "menu_advanced": "Расширенные параметры",
        "menu_advanced_hint": "Селекторы, область, водяные знаки и диагностика",
        "menu_quit": "Выход",
        "choice": "Выбор",
        "invalid_choice": "Неверный выбор. Используйте 1, 2 или 3.",
        "source_title": "Источник",
        "url_prompt": "URL публикации",
        "url_missing": "URL не указан.",
        "output_title": "Результат",
        "output_prompt": "Корневая папка",
        "format_title": "Итоговый формат",
        "format_original": "Оригинал",
        "format_original_hint": "Исходный PDF/EPUB, иначе CBZ с оригинальными изображениями",
        "format_cbz_hint": "ZIP-архив для манги, комиксов и изображений страниц",
        "format_cbr_hint": "RAR-архив; требуется WinRAR или rar",
        "format_pdf_hint": "Исходный документ или PDF с фиксированной разметкой",
        "format_epub_hint": "Исходная книга или EPUB с фиксированной разметкой",
        "format_images_hint": "Исходные файлы в отдельной папке",
        "format_prompt": "Формат",
        "format_invalid": "Неверный формат. Выберите число от 1 до 6.",
        "manual_login": "Сайт требует ручного входа?",
        "advanced_title": "Расширенные настройки",
        "scope_prompt": "Область (auto, document или work)",
        "scope_invalid": "Неверная область: auto, document или work.",
        "selector_prompt": "CSS-селектор страниц",
        "expected_prompt": "Ожидаемое число страниц",
        "expected_invalid": "Число страниц должно быть положительным целым.",
        "reading_selector_prompt": "Селектор режима чтения",
        "reading_value_prompt": "Значение режима чтения",
        "watermark_prompt": "Водяные знаки SVG (remove или detect)",
        "watermark_invalid": "Выберите remove или detect.",
        "watermark_text_prompt": "Дополнительный точный текст для удаления",
        "summary_title": "Готово к запуску",
        "label_url": "URL",
        "label_output": "Папка",
        "label_format": "Формат",
        "label_mode": "Режим",
        "auto_title_placeholder": "<определённое название>",
        "inspect_mode": "только проверка; загрузка отключена",
        "cancelled": "Операция отменена.",
        "error": "ОШИБКА",
        "missing_url_cli": "URL не указан. Добавьте URL или откройте интерактивное меню.",
        "invalid_url": "URL должен начинаться с http:// или https://",
        "markdown_mismatch": "Текст и адрес Markdown-ссылки различаются. Вставьте нужный URL напрямую.",
        "pdf_conflict": "Используйте --pdf или --format, но не оба параметра.",
    },
    "zh": {
        "tagline": "将网页出版物转换为整洁、易读的归档文件。",
        "authorization": "仅用于您拥有或获准归档的内容。",
        "language_title": "语言 / Language / Langue / Язык",
        "language_prompt": "语言",
        "language_invalid": "请选择 1、2、3 或 4。",
        "menu_title": "您想做什么？",
        "menu_auto": "引导式提取",
        "menu_auto_hint": "自动检测，仅显示必要设置",
        "menu_advanced": "高级选项",
        "menu_advanced_hint": "选择器、范围、水印和诊断",
        "menu_quit": "退出",
        "choice": "选择",
        "invalid_choice": "选择无效。请输入 1、2 或 3。",
        "source_title": "来源",
        "url_prompt": "出版物 URL",
        "url_missing": "未提供 URL。",
        "output_title": "输出",
        "output_prompt": "根目录",
        "format_title": "最终格式",
        "format_original": "原始格式",
        "format_original_hint": "保留原生 PDF/EPUB；图片页面则生成含原图的 CBZ",
        "format_cbz_hint": "适用于漫画和图片页面的 ZIP 归档",
        "format_cbr_hint": "RAR 归档；需要 WinRAR 或 rar",
        "format_pdf_hint": "保留原文档或从页面生成固定版式 PDF",
        "format_epub_hint": "保留原电子书或生成固定版式 EPUB",
        "format_images_hint": "将原始文件保存在文件夹中",
        "format_prompt": "格式",
        "format_invalid": "格式无效。请输入 1 到 6。",
        "manual_login": "网站是否需要手动登录？",
        "advanced_title": "高级设置",
        "scope_prompt": "范围（auto、document 或 work）",
        "scope_invalid": "范围无效：仅支持 auto、document 或 work。",
        "selector_prompt": "页面 CSS 选择器",
        "expected_prompt": "预计页数",
        "expected_invalid": "页数必须是正整数。",
        "reading_selector_prompt": "阅读模式选择器",
        "reading_value_prompt": "阅读模式值",
        "watermark_prompt": "SVG 水印（remove 或 detect）",
        "watermark_invalid": "请选择 remove 或 detect。",
        "watermark_text_prompt": "要额外删除的精确文本",
        "summary_title": "准备开始",
        "label_url": "URL",
        "label_output": "输出",
        "label_format": "格式",
        "label_mode": "模式",
        "auto_title_placeholder": "<检测到的标题>",
        "inspect_mode": "仅检查；不会下载任何内容",
        "cancelled": "操作已取消。",
        "error": "错误",
        "missing_url_cli": "缺少 URL。请添加 URL 或启动交互式菜单。",
        "invalid_url": "URL 必须以 http:// 或 https:// 开头",
        "markdown_mismatch": "Markdown 链接的文本与目标地址不同。请直接粘贴所需 URL。",
        "pdf_conflict": "请使用 --pdf 或 --format，不要同时使用。",
    },
}


def normalize_language(value: str | None, default: str = "fr") -> str:
    normalized = (value or "").strip().casefold()
    aliases = {
        "1": "fr", "fr": "fr", "fra": "fr", "français": "fr", "francais": "fr",
        "2": "en", "en": "en", "eng": "en", "english": "en",
        "3": "ru", "ru": "ru", "rus": "ru", "русский": "ru",
        "4": "zh", "zh": "zh", "cn": "zh", "中文": "zh", "chinese": "zh",
    }
    return aliases.get(normalized, default)


def tr(language: str, key: str, **values: object) -> str:
    catalog = MESSAGES.get(language, MESSAGES["fr"])
    template = catalog.get(key, MESSAGES["fr"].get(key, key))
    return template.format(**values)


RUNTIME_MESSAGES: dict[str, dict[str, str]] = {
    "opening": {"fr": "Ouverture : {value}", "en": "Opening: {value}", "ru": "Открытие: {value}", "zh": "正在打开：{value}"},
    "site_profile": {"fr": "Profil du site : {value}", "en": "Site profile: {value}", "ru": "Профиль сайта: {value}", "zh": "网站配置：{value}"},
    "work": {"fr": "Œuvre : {value}", "en": "Work: {value}", "ru": "Произведение: {value}", "zh": "作品：{value}"},
    "structure": {"fr": "Structure : {value}", "en": "Structure: {value}", "ru": "Структура: {value}", "zh": "结构：{value}"},
    "parts_detected": {"fr": "{label} détectés : {count}", "en": "{label} detected: {count}", "ru": "Обнаружено — {label}: {count}", "zh": "检测到{label}：{count}"},
    "parts_selected": {"fr": "{label} sélectionnés : {count}", "en": "{label} selected: {count}", "ru": "Выбрано — {label}: {count}", "zh": "已选择{label}：{count}"},
    "detected_title": {"fr": "Titre détecté : {value}", "en": "Detected title: {value}", "ru": "Определённое название: {value}", "zh": "检测到的标题：{value}"},
    "planned_folder": {"fr": "Dossier prévu : {value}", "en": "Planned folder: {value}", "ru": "Планируемая папка: {value}", "zh": "计划目录：{value}"},
    "final_folder": {"fr": "Dossier final : {value}", "en": "Final folder: {value}", "ru": "Итоговая папка: {value}", "zh": "最终目录：{value}"},
    "part_heading": {"fr": "{label} {index} : {title}", "en": "{label} {index}: {title}", "ru": "{label} {index}: {title}", "zh": "{label} {index}：{title}"},
    "reading_mode": {"fr": "Mode de lecture : {value}", "en": "Reading mode: {value}", "ru": "Режим чтения: {value}", "zh": "阅读模式：{value}"},
    "progressive_loading": {"fr": "Chargement progressif : {images} image(s), {steps} étape(s)", "en": "Progressive loading: {images} image(s), {steps} step(s)", "ru": "Постепенная загрузка: изображений {images}, шагов {steps}", "zh": "渐进加载：{images} 张图片，{steps} 个步骤"},
    "detection": {"fr": "Détection : {value}", "en": "Detection: {value}", "ru": "Определение: {value}", "zh": "检测方式：{value}"},
    "resources_found": {"fr": "Ressources de page trouvées : {count}", "en": "Page resources found: {count}", "ru": "Найдено ресурсов страниц: {count}", "zh": "找到页面资源：{count}"},
    "pages_expected": {"fr": "Pages attendues : {count} ({source})", "en": "Expected pages: {count} ({source})", "ru": "Ожидается страниц: {count} ({source})", "zh": "预计页数：{count}（{source}）"},
    "visible_counter_ignored": {"fr": "Compteur visible {visible} ignoré : la séquence continue contient {count} pages.", "en": "Visible counter {visible} ignored: the continuous sequence contains {count} pages.", "ru": "Видимый счётчик {visible} проигнорирован: непрерывная последовательность содержит {count} страниц.", "zh": "已忽略可见计数 {visible}：连续序列包含 {count} 页。"},
    "domains": {"fr": "Domaines détectés : {value}", "en": "Detected domains: {value}", "ru": "Обнаруженные домены: {value}", "zh": "检测到的域名：{value}"},
    "inspection_complete": {"fr": "Inspection terminée : aucun fichier téléchargé.", "en": "Inspection complete: no files were downloaded.", "ru": "Проверка завершена: файлы не загружались.", "zh": "检查完成：未下载任何文件。"},
    "inspection_incomplete": {"fr": "[ANNULÉ] Inspection incomplète : aucune publication ne serait créée.", "en": "[CANCELLED] Incomplete inspection: no publication would be created.", "ru": "[ОТМЕНЕНО] Проверка неполная: публикация не будет создана.", "zh": "[已取消] 检查不完整：不会创建出版物。"},
    "result": {"fr": "Résultat : {value}", "en": "Result: {value}", "ru": "Результат: {value}", "zh": "结果：{value}"},
    "manifest": {"fr": "Manifeste : {value}", "en": "Manifest: {value}", "ru": "Манифест: {value}", "zh": "清单：{value}"},
    "consent": {"fr": "Consentement : {value}", "en": "Consent: {value}", "ru": "Согласие: {value}", "zh": "Cookie 同意：{value}"},
    "reader_start": {"fr": "Démarrage du lecteur : {value}", "en": "Reader started: {value}", "ru": "Запуск читалки: {value}", "zh": "阅读器已启动：{value}"},
    "reader_initialization": {"fr": "Initialisation du lecteur : {seconds:.1f} s", "en": "Reader initialization: {seconds:.1f} s", "ru": "Инициализация читалки: {seconds:.1f} с", "zh": "阅读器初始化：{seconds:.1f} 秒"},
    "access_check": {"fr": "Vérification du site terminée : {seconds:.1f} s", "en": "Site verification complete: {seconds:.1f} s", "ru": "Проверка сайта завершена: {seconds:.1f} с", "zh": "网站验证完成：{seconds:.1f} 秒"},
    "linked_reader": {"fr": "Lecteur lié détecté : {action} -> {url}", "en": "Linked reader detected: {action} -> {url}", "ru": "Обнаружена связанная читалка: {action} -> {url}", "zh": "检测到关联阅读器：{action} -> {url}"},
    "epub_loaded": {"fr": "Ressource EPUB : réponse déjà chargée par le navigateur", "en": "EPUB resource: response already loaded by the browser", "ru": "Ресурс EPUB: ответ уже загружен браузером", "zh": "EPUB 资源：浏览器已加载响应"},
    "epub_detection": {"fr": "Détection : ressource EPUB chargée par le navigateur", "en": "Detection: EPUB resource loaded by the browser", "ru": "Определение: ресурс EPUB загружен браузером", "zh": "检测：浏览器已加载 EPUB 资源"},
    "document_resource": {"fr": "Ressource documentaire : {size:.1f} Mo", "en": "Document resource: {size:.1f} MB", "ru": "Размер документа: {size:.1f} МБ", "zh": "文档资源：{size:.1f} MB"},
    "epub_sections": {"fr": "Sections EPUB dans l’ordre de lecture : {count} (sans nombre de pages fixe)", "en": "EPUB sections in reading order: {count} (no fixed page count)", "ru": "Разделов EPUB в порядке чтения: {count} (фиксированного числа страниц нет)", "zh": "EPUB 阅读顺序章节：{count}（无固定页数）"},
    "epub_toc": {"fr": "Documents annoncés par la table des matières EPUB : {present}/{total} présents", "en": "Documents announced by the EPUB table of contents: {present}/{total} present", "ru": "Документы из оглавления EPUB: присутствует {present}/{total}", "zh": "EPUB 目录声明的文档：存在 {present}/{total}"},
    "epub_incomplete": {"fr": "[INCOMPLET] EPUB : {missing} document(s) annoncé(s) sont absents.", "en": "[INCOMPLETE] EPUB: {missing} announced document(s) are missing.", "ru": "[НЕПОЛНО] EPUB: отсутствует заявленных документов — {missing}.", "zh": "[不完整] EPUB：缺少 {missing} 个声明的文档。"},
    "epub_no_orphans": {"fr": "Diagnostic EPUB : aucun fichier local détaché ni donnée ajoutée n’a été trouvé.", "en": "EPUB diagnostic: no detached local file or appended data was found.", "ru": "Диагностика EPUB: отделённых локальных файлов и добавленных данных не найдено.", "zh": "EPUB 诊断：未发现分离的本地文件或追加数据。"},
    "extraction_refused": {"fr": "[ANNULÉ] Extraction refusée : {present}/{total} document(s), {missing} manquant(s).", "en": "[CANCELLED] Extraction refused: {present}/{total} document(s), {missing} missing.", "ru": "[ОТМЕНЕНО] Извлечение отклонено: {present}/{total} документов, отсутствует {missing}.", "zh": "[已取消] 拒绝提取：{present}/{total} 个文档，缺少 {missing} 个。"},
    "catalog": {"fr": "Catalogue Manga UP : {accessible} sous-partie(s) accessible(s) sur {total} annoncée(s)", "en": "Manga UP catalog: {accessible} accessible part(s) out of {total}", "ru": "Каталог Manga UP: доступно частей {accessible} из {total}", "zh": "Manga UP 目录：{total} 个部分中可访问 {accessible} 个"},
    "source_limit": {"fr": "[LIMITÉ PAR LA SOURCE] Seules les parties accessibles dans cette session seront proposées.", "en": "[SOURCE LIMITED] Only parts accessible in this session will be offered.", "ru": "[ОГРАНИЧЕНО ИСТОЧНИКОМ] Будут предложены только доступные в этой сессии части.", "zh": "[来源受限] 仅提供当前会话可访问的部分。"},
    "source_result": {"fr": "[RÉSULTAT LIMITÉ PAR LA SOURCE] {accessible}/{total} partie(s) accessibles.", "en": "[SOURCE-LIMITED RESULT] {accessible}/{total} part(s) accessible.", "ru": "[РЕЗУЛЬТАТ ОГРАНИЧЕН ИСТОЧНИКОМ] Доступно {accessible}/{total} частей.", "zh": "[来源受限结果] 可访问 {accessible}/{total} 个部分。"},
}


def rt(language: str, key: str, **values: object) -> str:
    language = normalize_language(language)
    translations = RUNTIME_MESSAGES[key]
    return translations.get(language, translations["fr"]).format(**values)


def ensure_utf8_stream(stream: TextIO) -> None:
    """Permet l'affichage russe/chinois dans les consoles Windows anciennes."""
    if os.name != "nt" or not hasattr(stream, "reconfigure"):
        return
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError, ValueError):
        pass


def display_width(value: str) -> int:
    """Largeur réellement occupée par du texte Unicode dans un terminal."""
    width = 0
    for character in value:
        if unicodedata.combining(character):
            continue
        width += 2 if unicodedata.east_asian_width(character) in {"W", "F"} else 1
    return width


@dataclass
class TerminalUI:
    language: str = "fr"
    stream: TextIO = field(default_factory=lambda: sys.stdout)

    def __post_init__(self) -> None:
        ensure_utf8_stream(self.stream)
        self.language = normalize_language(self.language)
        self.color = bool(
            getattr(self.stream, "isatty", lambda: False)()
            and not os.environ.get("NO_COLOR")
            and os.environ.get("TERM", "").casefold() != "dumb"
        )
        self.animation = bool(
            self.color
            and not os.environ.get("CI")
            and not os.environ.get("KOMAFORGE_NO_ANIMATION")
            and not os.environ.get("KOMAFORGE_REDUCE_MOTION")
        )

    def _style(self, value: str, code: str) -> str:
        return f"\033[{code}m{value}\033[0m" if self.color else value

    def text(self, key: str, **values: object) -> str:
        return tr(self.language, key, **values)

    def _print_brand_frame(self, frame: tuple[str, ...]) -> None:
        for line, color in zip(frame, BRAND_ART_COLORS):
            print(self._style(line, color), file=self.stream)

    def _brand(self) -> None:
        if not self.animation:
            self._print_brand_frame(BRAND_ART)
            return

        self.stream.write("\033[?25l")
        try:
            for index, frame in enumerate(BRAND_FRAMES):
                if index:
                    self.stream.write(f"\033[{BRAND_HEIGHT}A\r\033[J")
                self._print_brand_frame(frame)
                self.stream.flush()
                if index < len(BRAND_FRAMES) - 1:
                    time.sleep(BRAND_FRAME_DELAY)
        finally:
            self.stream.write("\033[?25h")
            self.stream.flush()

    def header(self) -> None:
        print(file=self.stream)
        self._brand()
        tagline = f"  {self.text('tagline')}"
        inner_width = max(50, display_width(tagline) + 2)
        padding = " " * (inner_width - display_width(tagline))
        print(self._style(f"╭{'─' * inner_width}╮", "1;36"), file=self.stream)
        print(f"{self._style('│', '36')}{tagline}{padding}{self._style('│', '36')}", file=self.stream)
        print(self._style(f"╰{'─' * inner_width}╯", "36"), file=self.stream)
        print(self._style(f"  {self.text('authorization')}", "2"), file=self.stream)

    def section(self, title: str) -> None:
        print(file=self.stream)
        print(self._style(f"── {title} ──", "1;34"), file=self.stream)

    def option(self, number: int, label: str, hint: str | None = None) -> None:
        print(f"  {self._style(f'[{number}]', '1;36')} {label}", file=self.stream)
        if hint:
            print(self._style(f"      {hint}", "2"), file=self.stream)

    def prompt(self, label: str, default: str | None = None) -> str:
        suffix = f" [{default}]" if default else ""
        return input(self._style(f"{label}{suffix} › ", "1;36")).strip()

    def key_value(self, label: str, value: object) -> None:
        print(f"  {self._style(label + ':', '1')} {value}", file=self.stream)

    def error(self, message: str) -> None:
        print(self._style(f"{self.text('error')} : {message}", "1;31"), file=self.stream)


def choose_language(default: str = "fr") -> str:
    ensure_utf8_stream(sys.stdout)
    default = normalize_language(default)
    print()
    print("── Language / Langue / Язык / 语言 ──")
    for index, code in enumerate(SUPPORTED_LANGUAGES, start=1):
        marker = " *" if code == default else ""
        print(f"  [{index}] {LANGUAGE_NAMES[code]}{marker}")
    answer = input(f"Language [{LANGUAGE_NAMES[default]}] › ").strip()
    if not answer:
        return default
    selected = normalize_language(answer, default="")
    if selected not in SUPPORTED_LANGUAGES:
        raise SystemExit(tr(default, "language_invalid"))
    return selected
