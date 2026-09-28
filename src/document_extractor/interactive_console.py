"""Interactive platform menus used by the desktop shortcut."""

from __future__ import annotations

from pathlib import Path

from .application import resolve_source
from .formats import OUTPUT_FORMATS
from .job_executor import JobExecutor
from .jobs import JobAction, JobQueue, JobStatus
from .library import SCHEMA_VERSION, LibraryIndex
from .library_service import LibraryService
from .library_state import LibraryState
from .paths import default_output_root
from .source_cli import (
    candidate_records,
    describe_source,
    family_records,
    source_records,
)
from .terminal_ui import TerminalUI


PLATFORM_MESSAGES = {
    "fr": {
        "top_sources": "Sources et compatibilité",
        "top_sources_hint": "Adaptateurs, familles de lecteurs et diagnostic d’URL",
        "top_library": "Bibliothèque locale",
        "top_library_hint": "Index, recherche, suivi et progression de lecture",
        "top_jobs": "File d’attente",
        "top_jobs_hint": "Inspections et téléchargements persistants",
        "top_invalid": "Choix invalide. Utilisez un nombre de 1 à 6.",
        "sources_title": "Sources et compatibilité",
        "sources_adapters": "Adaptateurs disponibles",
        "sources_families": "Familles de lecteurs",
        "sources_candidates": "Sites génériques validés",
        "sources_match": "Identifier la source d’une URL",
        "back": "Retour au menu principal",
        "submenu_invalid": "Choix invalide.",
        "url": "URL",
        "status": "État",
        "compatibility": "Compatibilité",
        "integration": "Intégration",
        "access": "Accès",
        "domains": "Domaines",
        "capabilities": "Capacités",
        "last_verified": "Dernière vérification",
        "route": "Routage",
        "confidence": "Confiance",
        "specialized": "spécialisé",
        "fallback": "secours générique",
        "never": "jamais",
        "unknown": "inconnu",
        "works": "Œuvres",
        "publications": "Publications",
        "parts": "Parties",
        "resources": "Ressources",
        "coverage": "Couverture",
        "integrity": "Intégrité",
        "tracked": "Suivies",
        "categories": "Catégories",
        "unread": "non lues",
        "completed": "terminées",
        "attempts": "tentatives",
        "pending": "En attente",
        "failed": "Échecs",
        "library_title": "Bibliothèque locale",
        "library_root": "Dossier",
        "library_status": "Tableau de bord",
        "library_browse": "Consulter",
        "library_actions": "Actions",
        "library_read": "Lire dans KomaForge",
        "library_open": "Ouvrir un téléchargement",
        "library_rebuild": "Reconstruire l’index",
        "library_list": "Lister les œuvres",
        "library_search": "Rechercher une œuvre",
        "library_publications": "Afficher les publications et identifiants",
        "library_tracked": "Afficher les publications suivies",
        "library_unread": "Afficher les parties non lues",
        "library_downloaded": "Afficher les téléchargements disponibles",
        "library_history": "Afficher l’historique de lecture",
        "library_categories": "Gérer les catégories",
        "category_list": "Lister les catégories",
        "category_create": "Créer une catégorie",
        "category_add": "Classer une publication",
        "category_remove": "Retirer une publication d’une catégorie",
        "category_delete": "Supprimer une catégorie",
        "category_members": "Afficher le contenu d’une catégorie",
        "category_name": "Nom de la catégorie",
        "category_empty": "Aucune catégorie.",
        "library_update": "Planifier les mises à jour des publications suivies",
        "library_add": "Ajouter une URL et suivre la publication",
        "library_track": "Suivre une publication",
        "library_untrack": "Ne plus suivre une publication",
        "library_progress": "Enregistrer la progression",
        "library_missing": "Index absent ou incompatible. Reconstruisez-le d’abord.",
        "library_empty": "Aucune œuvre indexée.",
        "publication_empty": "Aucune publication indexée.",
        "tracked_empty": "Aucune publication suivie.",
        "unread_empty": "Aucune partie non lue.",
        "history_empty": "Aucun historique de lecture.",
        "query": "Recherche",
        "publication_id": "Identifiant de publication",
        "part_id": "Identifiant de partie",
        "position": "Position de la ressource",
        "complete": "Partie terminée ?",
        "yes_no": "o/N",
        "jobs_title": "File d’attente persistante",
        "jobs_path": "Fichier",
        "jobs_list": "Afficher les travaux",
        "jobs_inspect": "Ajouter une inspection",
        "jobs_download": "Ajouter un téléchargement",
        "jobs_update": "Ajouter une vérification de mise à jour",
        "jobs_run": "Exécuter le prochain travail",
        "jobs_run_all": "Exécuter toute la file",
        "jobs_retry": "Relancer un travail échoué",
        "jobs_cancel": "Annuler un travail en attente",
        "jobs_recover": "Récupérer les travaux interrompus",
        "jobs_empty": "Aucun travail dans la file.",
        "job_id": "Identifiant du travail",
        "format": "Format",
        "scope": "Portée",
        "chapters": "Parties",
        "created": "Travail ajouté",
        "recovered": "Travaux récupérés",
        "nothing_run": "Aucun travail inspect, download ou update en attente.",
    },
    "en": {
        "top_sources": "Sources and compatibility",
        "top_sources_hint": "Adapters, reader families, and URL diagnostics",
        "top_library": "Local library",
        "top_library_hint": "Index, search, tracking, and reading progress",
        "top_jobs": "Job queue",
        "top_jobs_hint": "Persistent inspections and downloads",
        "top_invalid": "Invalid choice. Use a number from 1 to 6.",
        "sources_title": "Sources and compatibility",
        "sources_adapters": "Available adapters",
        "sources_families": "Reader families",
        "sources_candidates": "Validated generic sites",
        "sources_match": "Identify the source for a URL",
        "back": "Back to the main menu",
        "submenu_invalid": "Invalid choice.",
        "url": "URL",
        "status": "Status",
        "compatibility": "Compatibility",
        "integration": "Integration",
        "access": "Access",
        "domains": "Domains",
        "capabilities": "Capabilities",
        "last_verified": "Last verified",
        "route": "Routing",
        "confidence": "Confidence",
        "specialized": "specialized",
        "fallback": "generic fallback",
        "never": "never",
        "unknown": "unknown",
        "works": "Works",
        "publications": "Publications",
        "parts": "Parts",
        "resources": "Resources",
        "coverage": "Coverage",
        "integrity": "Integrity",
        "tracked": "Tracked",
        "categories": "Categories",
        "unread": "unread",
        "completed": "completed",
        "attempts": "attempts",
        "pending": "Pending",
        "failed": "Failed",
        "library_title": "Local library",
        "library_root": "Folder",
        "library_status": "Dashboard",
        "library_browse": "Browse",
        "library_actions": "Actions",
        "library_read": "Read in KomaForge",
        "library_open": "Open a download",
        "library_rebuild": "Rebuild the index",
        "library_list": "List works",
        "library_search": "Search works",
        "library_publications": "Show publications and identifiers",
        "library_tracked": "Show tracked publications",
        "library_unread": "Show unread parts",
        "library_downloaded": "Show downloaded publications",
        "library_history": "Show reading history",
        "library_categories": "Manage categories",
        "category_list": "List categories",
        "category_create": "Create a category",
        "category_add": "Assign a publication",
        "category_remove": "Remove a publication from a category",
        "category_delete": "Delete a category",
        "category_members": "Show category contents",
        "category_name": "Category name",
        "category_empty": "No categories.",
        "library_update": "Queue updates for tracked publications",
        "library_add": "Add a URL and track the publication",
        "library_track": "Track a publication",
        "library_untrack": "Stop tracking a publication",
        "library_progress": "Record reading progress",
        "library_missing": "The index is missing or incompatible. Rebuild it first.",
        "library_empty": "No indexed works.",
        "publication_empty": "No indexed publications.",
        "tracked_empty": "No tracked publications.",
        "unread_empty": "No unread parts.",
        "history_empty": "No reading history.",
        "query": "Search",
        "publication_id": "Publication identifier",
        "part_id": "Part identifier",
        "position": "Resource position",
        "complete": "Part completed?",
        "yes_no": "y/N",
        "jobs_title": "Persistent job queue",
        "jobs_path": "File",
        "jobs_list": "Show jobs",
        "jobs_inspect": "Add an inspection",
        "jobs_download": "Add a download",
        "jobs_update": "Add an update check",
        "jobs_run": "Run the next job",
        "jobs_run_all": "Run the entire queue",
        "jobs_retry": "Retry a failed job",
        "jobs_cancel": "Cancel a pending job",
        "jobs_recover": "Recover interrupted jobs",
        "jobs_empty": "The queue is empty.",
        "job_id": "Job identifier",
        "format": "Format",
        "scope": "Scope",
        "chapters": "Parts",
        "created": "Job added",
        "recovered": "Recovered jobs",
        "nothing_run": "No pending inspect, download, or update job.",
    },
    "ru": {
        "top_sources": "Источники и совместимость",
        "top_sources_hint": "Адаптеры, типы читалок и проверка URL",
        "top_library": "Локальная библиотека",
        "top_library_hint": "Индекс, поиск, отслеживание и прогресс",
        "top_jobs": "Очередь заданий",
        "top_jobs_hint": "Сохраняемые проверки и загрузки",
        "top_invalid": "Неверный выбор. Используйте число от 1 до 6.",
        "sources_title": "Источники и совместимость",
        "sources_adapters": "Доступные адаптеры",
        "sources_families": "Типы читалок",
        "sources_candidates": "Проверенные универсальные сайты",
        "sources_match": "Определить источник по URL",
        "back": "Назад в главное меню",
        "submenu_invalid": "Неверный выбор.",
        "url": "URL",
        "status": "Статус",
        "compatibility": "Совместимость",
        "integration": "Интеграция",
        "access": "Доступ",
        "domains": "Домены",
        "capabilities": "Возможности",
        "last_verified": "Последняя проверка",
        "route": "Маршрут",
        "confidence": "Уверенность",
        "specialized": "специализированный",
        "fallback": "универсальный резерв",
        "never": "никогда",
        "unknown": "неизвестно",
        "works": "Произведения",
        "publications": "Публикации",
        "parts": "Части",
        "resources": "Ресурсы",
        "coverage": "Покрытие",
        "integrity": "Целостность",
        "tracked": "Отслеживается",
        "categories": "Категории",
        "unread": "не прочитано",
        "completed": "завершено",
        "attempts": "попытки",
        "pending": "Ожидает",
        "failed": "Ошибки",
        "library_title": "Локальная библиотека",
        "library_root": "Папка",
        "library_status": "Состояние",
        "library_browse": "Просмотр",
        "library_actions": "Действия",
        "library_read": "Читать в KomaForge",
        "library_open": "Открыть загрузку",
        "library_rebuild": "Перестроить индекс",
        "library_list": "Список произведений",
        "library_search": "Поиск произведения",
        "library_publications": "Публикации и идентификаторы",
        "library_tracked": "Отслеживаемые публикации",
        "library_unread": "Непрочитанные части",
        "library_downloaded": "Загруженные публикации",
        "library_history": "История чтения",
        "library_categories": "Управление категориями",
        "category_list": "Список категорий",
        "category_create": "Создать категорию",
        "category_add": "Добавить публикацию в категорию",
        "category_remove": "Удалить публикацию из категории",
        "category_delete": "Удалить категорию",
        "category_members": "Содержимое категории",
        "category_name": "Название категории",
        "category_empty": "Категорий нет.",
        "library_update": "Проверить обновления отслеживаемых публикаций",
        "library_add": "Добавить URL и отслеживать публикацию",
        "library_track": "Начать отслеживание",
        "library_untrack": "Прекратить отслеживание",
        "library_progress": "Сохранить прогресс",
        "library_missing": "Индекс отсутствует или несовместим. Сначала перестройте его.",
        "library_empty": "В индексе нет произведений.",
        "publication_empty": "В индексе нет публикаций.",
        "tracked_empty": "Нет отслеживаемых публикаций.",
        "unread_empty": "Нет непрочитанных частей.",
        "history_empty": "История чтения пуста.",
        "query": "Поиск",
        "publication_id": "ID публикации",
        "part_id": "ID части",
        "position": "Позиция ресурса",
        "complete": "Часть завершена?",
        "yes_no": "д/Н",
        "jobs_title": "Сохраняемая очередь",
        "jobs_path": "Файл",
        "jobs_list": "Показать задания",
        "jobs_inspect": "Добавить проверку",
        "jobs_download": "Добавить загрузку",
        "jobs_update": "Добавить проверку обновлений",
        "jobs_run": "Выполнить следующее задание",
        "jobs_run_all": "Выполнить всю очередь",
        "jobs_retry": "Повторить ошибочное задание",
        "jobs_cancel": "Отменить ожидающее задание",
        "jobs_recover": "Восстановить прерванные задания",
        "jobs_empty": "Очередь пуста.",
        "job_id": "ID задания",
        "format": "Формат",
        "scope": "Область",
        "chapters": "Части",
        "created": "Задание добавлено",
        "recovered": "Восстановлено заданий",
        "nothing_run": "Нет ожидающих проверок, загрузок или обновлений.",
    },
    "zh": {
        "top_sources": "来源与兼容性",
        "top_sources_hint": "适配器、阅读器类型和 URL 诊断",
        "top_library": "本地书库",
        "top_library_hint": "索引、搜索、跟踪和阅读进度",
        "top_jobs": "任务队列",
        "top_jobs_hint": "持久化检查和下载",
        "top_invalid": "选择无效。请输入 1 到 6。",
        "sources_title": "来源与兼容性",
        "sources_adapters": "可用适配器",
        "sources_families": "阅读器类型",
        "sources_candidates": "已验证的通用网站",
        "sources_match": "识别 URL 来源",
        "back": "返回主菜单",
        "submenu_invalid": "选择无效。",
        "url": "URL",
        "status": "状态",
        "compatibility": "兼容性",
        "integration": "集成方式",
        "access": "访问条件",
        "domains": "域名",
        "capabilities": "能力",
        "last_verified": "上次验证",
        "route": "路由",
        "confidence": "置信度",
        "specialized": "专用",
        "fallback": "通用后备",
        "never": "从未",
        "unknown": "未知",
        "works": "作品",
        "publications": "出版物",
        "parts": "部分",
        "resources": "资源",
        "coverage": "覆盖率",
        "integrity": "完整性",
        "tracked": "已跟踪",
        "categories": "分类",
        "unread": "未读",
        "completed": "已完成",
        "attempts": "尝试次数",
        "pending": "等待中",
        "failed": "失败",
        "library_title": "本地书库",
        "library_root": "文件夹",
        "library_status": "概览",
        "library_browse": "浏览",
        "library_actions": "操作",
        "library_read": "在 KomaForge 中阅读",
        "library_open": "打开下载内容",
        "library_rebuild": "重建索引",
        "library_list": "列出作品",
        "library_search": "搜索作品",
        "library_publications": "显示出版物和标识符",
        "library_tracked": "显示已跟踪出版物",
        "library_unread": "显示未读部分",
        "library_downloaded": "显示已下载出版物",
        "library_history": "显示阅读历史",
        "library_categories": "管理分类",
        "category_list": "列出分类",
        "category_create": "创建分类",
        "category_add": "将出版物加入分类",
        "category_remove": "从分类中移除出版物",
        "category_delete": "删除分类",
        "category_members": "显示分类内容",
        "category_name": "分类名称",
        "category_empty": "暂无分类。",
        "library_update": "为已跟踪出版物安排更新",
        "library_add": "添加 URL 并跟踪出版物",
        "library_track": "跟踪出版物",
        "library_untrack": "停止跟踪出版物",
        "library_progress": "记录阅读进度",
        "library_missing": "索引不存在或不兼容。请先重建。",
        "library_empty": "没有已索引作品。",
        "publication_empty": "没有已索引出版物。",
        "tracked_empty": "没有已跟踪出版物。",
        "unread_empty": "没有未读部分。",
        "history_empty": "没有阅读历史。",
        "query": "搜索",
        "publication_id": "出版物标识符",
        "part_id": "部分标识符",
        "position": "资源位置",
        "complete": "该部分已完成？",
        "yes_no": "是/否",
        "jobs_title": "持久任务队列",
        "jobs_path": "文件",
        "jobs_list": "显示任务",
        "jobs_inspect": "添加检查",
        "jobs_download": "添加下载",
        "jobs_update": "添加更新检查",
        "jobs_run": "执行下一个任务",
        "jobs_run_all": "执行整个队列",
        "jobs_retry": "重试失败任务",
        "jobs_cancel": "取消等待任务",
        "jobs_recover": "恢复中断任务",
        "jobs_empty": "队列为空。",
        "job_id": "任务标识符",
        "format": "格式",
        "scope": "范围",
        "chapters": "部分",
        "created": "已添加任务",
        "recovered": "已恢复任务",
        "nothing_run": "没有等待中的检查、下载或更新任务。",
    },
}


def _text(ui: TerminalUI, key: str) -> str:
    return PLATFORM_MESSAGES.get(ui.language, PLATFORM_MESSAGES["fr"]).get(
        key,
        PLATFORM_MESSAGES["fr"].get(key, key),
    )


def _format_mapping(value: object) -> str:
    if not isinstance(value, dict):
        return str(value)
    return ", ".join(f"{key}={count}" for key, count in value.items()) or "—"


def _yes(value: str) -> bool:
    return value.strip().casefold() in {"o", "oui", "y", "yes", "д", "да", "是", "1"}


def _show_sources(ui: TerminalUI) -> None:
    ui.section(_text(ui, "sources_adapters"))
    for source in source_records():
        capabilities = ", ".join(
            name for name, enabled in source["capabilities"].items() if enabled
        )
        ui.item(
            f"{source['name']} · {source['compatibility']}",
            f"{source['integration']} · {source['access']} · "
            f"{', '.join(source['domains'])} · {capabilities} · "
            f"{source['last_verified'] or _text(ui, 'never')}",
        )


def _show_families(ui: TerminalUI) -> None:
    ui.section(_text(ui, "sources_families"))
    for family in family_records():
        ui.item(
            f"{family['name']} · {family['status']}",
            family["description"],
        )


def _show_candidates(ui: TerminalUI) -> None:
    ui.section(_text(ui, "sources_candidates"))
    for candidate in candidate_records():
        ui.item(
            f"{candidate['name']} · {candidate['compatibility']}",
            f"{candidate['integration']} · {candidate['access']} · "
            f"{', '.join(candidate['domains'])} · {candidate['adapter_id']} · "
            f"{candidate['last_verified'] or _text(ui, 'never')}",
        )


def _match_source(ui: TerminalUI) -> None:
    url = ui.prompt(_text(ui, "url"))
    if not url:
        return
    route = resolve_source(url)
    source = describe_source(route.adapter, specialized=route.specialized)
    ui.section(_text(ui, "route"))
    ui.key_value(_text(ui, "route"), source["name"])
    ui.key_value(_text(ui, "compatibility"), source["compatibility"])
    ui.key_value(_text(ui, "integration"), source["integration"])
    ui.key_value(_text(ui, "access"), source["access"])
    ui.key_value(_text(ui, "domains"), ", ".join(source["domains"]))
    ui.key_value(_text(ui, "confidence"), route.match.confidence.value)
    ui.key_value(_text(ui, "capabilities"), route.match.reason or "—")


def sources_menu(ui: TerminalUI) -> None:
    while True:
        ui.section(_text(ui, "sources_title"))
        ui.option(1, _text(ui, "sources_adapters"))
        ui.option(2, _text(ui, "sources_families"))
        ui.option(3, _text(ui, "sources_candidates"))
        ui.option(4, _text(ui, "sources_match"))
        ui.option(5, _text(ui, "back"))
        choice = ui.prompt(ui.text("choice"), "1") or "1"
        if choice == "5":
            return
        try:
            if choice == "1":
                _show_sources(ui)
            elif choice == "2":
                _show_families(ui)
            elif choice == "3":
                _show_candidates(ui)
            elif choice == "4":
                _match_source(ui)
            else:
                ui.error(_text(ui, "submenu_invalid"))
        except (RuntimeError, ValueError) as exc:
            ui.error(str(exc))


def _library_ready(ui: TerminalUI, index: LibraryIndex, root: Path) -> bool:
    if index.schema_version() == SCHEMA_VERSION:
        return True
    summary = index.rebuild(root)
    ui.notice(_text(ui, "library_rebuild"), "success")
    ui.key_value(_text(ui, "works"), summary.works)
    ui.key_value(_text(ui, "publications"), summary.publications)
    return True


def _show_library_status(
    ui: TerminalUI,
    index: LibraryIndex,
    state: LibraryState,
    root: Path,
) -> None:
    if not _library_ready(ui, index, root):
        return
    status = index.status()
    ui.section(_text(ui, "library_status"))
    ui.key_value(_text(ui, "works"), status["works"])
    ui.key_value(_text(ui, "publications"), status["publications"])
    ui.key_value(_text(ui, "parts"), status["parts"])
    ui.key_value(_text(ui, "resources"), status["resources"])
    ui.key_value(_text(ui, "coverage"), _format_mapping(status["coverage"]))
    ui.key_value(_text(ui, "integrity"), _format_mapping(status["artifact_integrity"]))
    service = LibraryService(index, state)
    ui.key_value(_text(ui, "tracked"), len(service.tracked()))
    ui.key_value(_text(ui, "categories"), len(state.categories()))
    ui.key_value(_text(ui, "unread"), len(service.unread()))
    jobs = JobQueue(root / ".komaforge" / "jobs.sqlite").list()
    ui.key_value(
        _text(ui, "pending"),
        sum(job.status is JobStatus.PENDING for job in jobs),
    )
    ui.key_value(
        _text(ui, "failed"),
        sum(job.status is JobStatus.FAILED for job in jobs),
    )


def _show_works(ui: TerminalUI, works: tuple[dict, ...]) -> None:
    if not works:
        ui.notice(_text(ui, "library_empty"), "info")
        return
    for work in works:
        ui.item(
            work["title"],
            f"{work['publication_count']} {_text(ui, 'publications').casefold()} · "
            f"{work['part_count']} {_text(ui, 'parts').casefold()}",
        )


def _show_publications(ui: TerminalUI, publications: tuple[dict, ...]) -> None:
    if not publications:
        ui.notice(_text(ui, "publication_empty"), "info")
        return
    for publication in publications:
        ui.item(
            publication["title"],
            f"{publication['id']} · "
            f"{publication['coverage_status'] or _text(ui, 'unknown')}",
        )


def _show_tracked(ui: TerminalUI, service: LibraryService) -> None:
    tracked = service.tracked()
    if not tracked:
        ui.notice(_text(ui, "tracked_empty"), "info")
        return
    for view in tracked:
        ui.item(
            view.publication.title,
            f"{view.publication.id} · {view.unread_parts} {_text(ui, 'unread')} · "
            f"{view.completed_parts} {_text(ui, 'completed')}",
        )


def _show_unread(ui: TerminalUI, service: LibraryService) -> None:
    unread = service.unread()
    if not unread:
        ui.notice(_text(ui, "unread_empty"), "info")
        return
    for item in unread:
        ui.item(
            item.part.title,
            f"{item.publication.title} · {item.part.id} · "
            f"{_text(ui, 'position')}={item.resource_position}",
        )


def _show_downloaded(ui: TerminalUI, index: LibraryIndex) -> None:
    publications = index.list_downloaded()
    if not publications:
        ui.notice(_text(ui, "publication_empty"), "info")
        return
    for publication in publications:
        ui.item(
            publication["title"],
            f"{publication['id']} · {publication['artifact_integrity']}",
        )


def _show_history(ui: TerminalUI, service: LibraryService) -> None:
    history = service.history()
    if not history:
        ui.notice(_text(ui, "history_empty"), "info")
        return
    for item in history:
        ui.item(
            item.part.title,
            f"{item.publication.title} · {_text(ui, 'position')}="
            f"{item.progress.resource_position} · {item.progress.updated_at}",
        )


def category_menu(
    ui: TerminalUI,
    state: LibraryState,
    service: LibraryService,
) -> None:
    while True:
        ui.section(_text(ui, "library_categories"))
        ui.option(1, _text(ui, "category_list"))
        ui.option(2, _text(ui, "category_members"))
        ui.option(3, _text(ui, "category_create"))
        ui.option(4, _text(ui, "category_add"))
        ui.option(5, _text(ui, "category_remove"))
        ui.option(6, _text(ui, "category_delete"))
        ui.option(7, _text(ui, "back"))
        choice = ui.prompt(ui.text("choice"), "1") or "1"
        if choice == "7":
            return
        try:
            if choice == "1":
                categories = state.categories()
                if not categories:
                    ui.notice(_text(ui, "category_empty"), "info")
                for category in categories:
                    ui.item(
                        category.name,
                        f"{len(state.category_members(category.name))} "
                        f"{_text(ui, 'publications').casefold()}",
                    )
            elif choice == "2":
                name = ui.prompt(_text(ui, "category_name"))
                publications = service.categorized(name)
                if not publications:
                    ui.notice(_text(ui, "publication_empty"), "info")
                for publication in publications:
                    ui.item(publication.title, publication.id)
            elif choice == "3":
                category = state.create_category(ui.prompt(_text(ui, "category_name")))
                ui.notice(f"{_text(ui, 'category_create')} : {category.name}", "success")
            elif choice == "4":
                name = ui.prompt(_text(ui, "category_name"))
                publication_id = ui.prompt(_text(ui, "publication_id"))
                if service.index.load_publication(publication_id) is None:
                    raise KeyError(publication_id)
                category = state.assign_category(publication_id, name)
                ui.notice(f"{_text(ui, 'category_add')} : {category.name}", "success")
            elif choice == "5":
                name = ui.prompt(_text(ui, "category_name"))
                publication_id = ui.prompt(_text(ui, "publication_id"))
                removed = state.remove_category(publication_id, name)
                ui.notice(_text(ui, "category_remove"), "success" if removed else "warning")
            elif choice == "6":
                removed = state.delete_category(ui.prompt(_text(ui, "category_name")))
                ui.notice(_text(ui, "category_delete"), "success" if removed else "warning")
            elif choice not in {str(value) for value in range(1, 8)}:
                ui.error(_text(ui, "submenu_invalid"))
        except (KeyError, OSError, RuntimeError, ValueError) as exc:
            ui.error(str(exc))


def library_menu(ui: TerminalUI, root: Path | None = None) -> None:
    library_root = (root or default_output_root()).expanduser().resolve()
    index = LibraryIndex(library_root / ".komaforge" / "library.sqlite")
    state = LibraryState(library_root / ".komaforge" / "state.sqlite")
    service = LibraryService(index, state)
    while True:
        ui.section(_text(ui, "library_title"))
        ui.key_value(_text(ui, "library_root"), library_root)
        ui.section(_text(ui, "library_browse"))
        ui.option(1, _text(ui, "library_status"))
        ui.option(2, _text(ui, "library_list"))
        ui.option(3, _text(ui, "library_search"))
        ui.option(4, _text(ui, "library_publications"))
        ui.option(5, _text(ui, "library_downloaded"))
        ui.option(6, _text(ui, "library_tracked"))
        ui.option(7, _text(ui, "library_unread"))
        ui.option(8, _text(ui, "library_history"))
        ui.section(_text(ui, "library_actions"))
        ui.option(9, _text(ui, "library_categories"))
        ui.option(10, _text(ui, "library_read"))
        ui.option(11, _text(ui, "library_open"))
        ui.option(12, _text(ui, "library_add"))
        ui.option(13, _text(ui, "library_update"))
        ui.option(14, _text(ui, "library_rebuild"))
        ui.option(15, _text(ui, "library_track"))
        ui.option(16, _text(ui, "library_untrack"))
        ui.option(17, _text(ui, "library_progress"))
        ui.option(18, _text(ui, "back"))
        choice = ui.prompt(ui.text("choice"), "1") or "1"
        if choice == "18":
            return
        try:
            if choice == "1":
                _show_library_status(ui, index, state, library_root)
            elif choice == "14":
                summary = index.rebuild(library_root)
                ui.notice(_text(ui, "library_rebuild"), "success")
                ui.key_value(_text(ui, "works"), summary.works)
                ui.key_value(_text(ui, "publications"), summary.publications)
                ui.key_value(_text(ui, "parts"), summary.parts)
                ui.key_value(_text(ui, "resources"), summary.resources)
            elif choice == "2" and _library_ready(ui, index, library_root):
                ui.section(_text(ui, "library_list"))
                _show_works(ui, index.list_works())
            elif choice == "3" and _library_ready(ui, index, library_root):
                query = ui.prompt(_text(ui, "query"))
                ui.section(_text(ui, "library_search"))
                _show_works(ui, index.search_works(query))
            elif choice == "4" and _library_ready(ui, index, library_root):
                ui.section(_text(ui, "library_publications"))
                _show_publications(ui, index.list_publications())
            elif choice == "5" and _library_ready(ui, index, library_root):
                ui.section(_text(ui, "library_downloaded"))
                _show_downloaded(ui, index)
            elif choice == "6" and _library_ready(ui, index, library_root):
                ui.section(_text(ui, "library_tracked"))
                _show_tracked(ui, service)
            elif choice == "7" and _library_ready(ui, index, library_root):
                ui.section(_text(ui, "library_unread"))
                _show_unread(ui, service)
            elif choice == "8" and _library_ready(ui, index, library_root):
                ui.section(_text(ui, "library_history"))
                _show_history(ui, service)
            elif choice == "13" and _library_ready(ui, index, library_root):
                queued = service.queue_updates(
                    JobQueue(library_root / ".komaforge" / "jobs.sqlite")
                )
                ui.notice(
                    f"{_text(ui, 'library_update')} : {len(queued)}",
                    "success",
                )
            elif choice == "9" and _library_ready(ui, index, library_root):
                category_menu(ui, state, service)
            elif choice == "10" and _library_ready(ui, index, library_root):
                publication_id = ui.prompt(_text(ui, "publication_id"))
                path = service.read_artifact(publication_id)
                ui.notice(f"{_text(ui, 'library_read')} : {path.name}", "success")
            elif choice == "11" and _library_ready(ui, index, library_root):
                publication_id = ui.prompt(_text(ui, "publication_id"))
                path = service.open_artifact(publication_id)
                ui.notice(f"{_text(ui, 'library_open')} : {path.name}", "success")
            elif choice == "12":
                source_url = ui.prompt(_text(ui, "url"))
                output_format = ui.prompt(_text(ui, "format"), "original").casefold()
                if output_format not in OUTPUT_FORMATS:
                    raise ValueError(f"unsupported format: {output_format}")
                scope = ui.prompt(_text(ui, "scope"), "auto").casefold()
                if scope not in {"auto", "document", "work"}:
                    raise ValueError(f"unsupported scope: {scope}")
                added = service.add_url(
                    source_url,
                    library_root,
                    options={
                        "chapters": ui.prompt(_text(ui, "chapters"), "all") or "all",
                        "language": ui.language,
                        "output_format": output_format,
                        "scope": scope,
                    },
                )
                ui.notice(
                    f"{_text(ui, 'library_add')} : {added.publication.title}",
                    "success",
                )
            elif choice == "15" and _library_ready(ui, index, library_root):
                publication_id = ui.prompt(_text(ui, "publication_id"))
                service.track(publication_id)
                ui.notice(_text(ui, "library_track"), "success")
            elif choice == "16" and _library_ready(ui, index, library_root):
                publication_id = ui.prompt(_text(ui, "publication_id"))
                removed = state.untrack(publication_id)
                ui.notice(
                    _text(ui, "library_untrack"),
                    "success" if removed else "warning",
                )
            elif choice == "17" and _library_ready(ui, index, library_root):
                publication_id = ui.prompt(_text(ui, "publication_id"))
                part_id = ui.prompt(_text(ui, "part_id"))
                position = int(ui.prompt(_text(ui, "position")))
                completed = _yes(
                    ui.prompt(_text(ui, "complete"), _text(ui, "yes_no"))
                )
                service.record_progress(
                    publication_id,
                    part_id,
                    position,
                    completed=completed,
                )
                ui.notice(_text(ui, "library_progress"), "success")
            elif choice not in {str(value) for value in range(1, 19)}:
                ui.error(_text(ui, "submenu_invalid"))
        except (KeyError, OSError, RuntimeError, ValueError) as exc:
            ui.error(str(exc))


def _show_jobs(ui: TerminalUI, queue: JobQueue) -> None:
    jobs = queue.list()
    if not jobs:
        ui.notice(_text(ui, "jobs_empty"), "info")
        return
    for job in jobs:
        ui.item(
            f"{job.action.value} · {job.status.value}",
            f"{job.id} · {job.source_id} · {_text(ui, 'attempts')}={job.attempts}",
        )


def _enqueue_job(ui: TerminalUI, queue: JobQueue, action: JobAction) -> None:
    url = ui.prompt(_text(ui, "url"))
    if not url:
        return
    options: dict[str, object] = {"language": ui.language}
    if action is JobAction.DOWNLOAD:
        output_format = ui.prompt(_text(ui, "format"), "original").casefold()
        if output_format not in OUTPUT_FORMATS:
            raise ValueError(f"unsupported format: {output_format}")
        scope = ui.prompt(_text(ui, "scope"), "auto").casefold()
        if scope not in {"auto", "document", "work"}:
            raise ValueError(f"unsupported scope: {scope}")
        options.update(
            {
                "output_format": output_format,
                "scope": scope,
                "chapters": ui.prompt(_text(ui, "chapters"), "all") or "all",
            }
        )
    job = queue.enqueue(action, url, options=options)
    ui.notice(f"{_text(ui, 'created')} : {job.id}", "success")


def jobs_menu(
    ui: TerminalUI,
    root: Path | None = None,
    queue_path: Path | None = None,
) -> None:
    output_root = (root or default_output_root()).expanduser().resolve()
    resolved_queue = (
        queue_path.expanduser().resolve()
        if queue_path
        else output_root / ".komaforge" / "jobs.sqlite"
    )
    queue = JobQueue(resolved_queue)
    while True:
        ui.section(_text(ui, "jobs_title"))
        ui.key_value(_text(ui, "jobs_path"), resolved_queue)
        ui.option(1, _text(ui, "jobs_list"))
        ui.option(2, _text(ui, "jobs_inspect"))
        ui.option(3, _text(ui, "jobs_download"))
        ui.option(4, _text(ui, "jobs_update"))
        ui.option(5, _text(ui, "jobs_run"))
        ui.option(6, _text(ui, "jobs_run_all"))
        ui.option(7, _text(ui, "jobs_retry"))
        ui.option(8, _text(ui, "jobs_cancel"))
        ui.option(9, _text(ui, "jobs_recover"))
        ui.option(10, _text(ui, "back"))
        choice = ui.prompt(ui.text("choice"), "1") or "1"
        if choice == "10":
            return
        try:
            if choice == "1":
                ui.section(_text(ui, "jobs_list"))
                _show_jobs(ui, queue)
            elif choice == "2":
                _enqueue_job(ui, queue, JobAction.INSPECT)
            elif choice == "3":
                _enqueue_job(ui, queue, JobAction.DOWNLOAD)
            elif choice == "4":
                _enqueue_job(ui, queue, JobAction.UPDATE)
            elif choice == "5":
                job = JobExecutor(queue).run_next()
                if job is None:
                    ui.notice(_text(ui, "nothing_run"), "info")
                else:
                    tone = "success" if job.status is JobStatus.COMPLETED else "warning"
                    ui.notice(f"{job.id} · {job.status.value}", tone)
            elif choice == "6":
                jobs = JobExecutor(queue).run_all()
                failures = sum(job.status is JobStatus.FAILED for job in jobs)
                ui.notice(
                    f"{_text(ui, 'jobs_run_all')} : {len(jobs)}",
                    "warning" if failures else "success",
                )
            elif choice == "7":
                job = queue.retry(ui.prompt(_text(ui, "job_id")))
                ui.notice(f"{job.id} · {job.status.value}", "success")
            elif choice == "8":
                job = queue.cancel(ui.prompt(_text(ui, "job_id")))
                ui.notice(f"{job.id} · {job.status.value}", "success")
            elif choice == "9":
                recovered = queue.recover_interrupted()
                ui.notice(f"{_text(ui, 'recovered')} : {recovered}", "success")
            else:
                ui.error(_text(ui, "submenu_invalid"))
        except (KeyError, OSError, RuntimeError, ValueError) as exc:
            ui.error(str(exc))


def interactive_hub(
    ui: TerminalUI,
    *,
    root: Path | None = None,
    queue_path: Path | None = None,
) -> str:
    """Return the selected extraction mode after handling platform submenus."""

    while True:
        ui.section(ui.text("menu_title"))
        ui.option(1, ui.text("menu_auto"), ui.text("menu_auto_hint"))
        ui.option(2, ui.text("menu_advanced"), ui.text("menu_advanced_hint"))
        ui.option(3, _text(ui, "top_sources"), _text(ui, "top_sources_hint"))
        ui.option(4, _text(ui, "top_library"), _text(ui, "top_library_hint"))
        ui.option(5, _text(ui, "top_jobs"), _text(ui, "top_jobs_hint"))
        ui.option(6, ui.text("menu_quit"))
        choice = ui.prompt(ui.text("choice"), "1") or "1"
        if choice == "1":
            return "guided"
        if choice == "2":
            return "advanced"
        if choice == "3":
            sources_menu(ui)
        elif choice == "4":
            library_menu(ui, root)
        elif choice == "5":
            jobs_menu(ui, root, queue_path)
        elif choice == "6":
            raise SystemExit(0)
        else:
            ui.error(_text(ui, "top_invalid"))
