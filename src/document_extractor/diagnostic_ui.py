"""Traduction des diagnostics humains ; les manifestes restent indépendants."""

from __future__ import annotations

import builtins
import re
from contextvars import ContextVar

_LANGUAGE = ContextVar("komaforge_diagnostic_language", default="fr")
_MESSAGES = [
  [
    "Format original retenu : PDF",
    {
      "fr": "Format original retenu : PDF",
      "en": "Original format selected: PDF",
      "ru": "Выбран исходный формат: PDF",
      "zh": "保留原始格式：PDF"
    }
  ],
  [
    "Format original retenu : EPUB",
    {
      "fr": "Format original retenu : EPUB",
      "en": "Original format selected: EPUB",
      "ru": "Выбран исходный формат: EPUB",
      "zh": "保留原始格式：EPUB"
    }
  ],
  [
    "Format original retenu : CBZ (pages image détectées)",
    {
      "fr": "Format original retenu : CBZ (pages image détectées)",
      "en": "Original format selected: CBZ (image pages detected)",
      "ru": "Выбран формат CBZ (обнаружены страницы-изображения)",
      "zh": "保留格式：CBZ（检测到图片页面）"
    }
  ],
  [
    "Rendu du lecteur : page {0}/{1}",
    {
      "fr": "Rendu du lecteur : page {0}/{1}",
      "en": "Reader rendering: page {0}/{1}",
      "ru": "Рендеринг читалки: страница {0}/{1}",
      "zh": "阅读器渲染：第 {0}/{1} 页"
    }
  ],
  [
    "Détection : ressource PDF chargée par le navigateur",
    {
      "fr": "Détection : ressource PDF chargée par le navigateur",
      "en": "Detection: PDF resource loaded by the browser",
      "ru": "Обнаружение: PDF загружен браузером",
      "zh": "检测到浏览器加载的 PDF 文件"
    }
  ],
  [
    "Ressource documentaire : {0} Mo",
    {
      "fr": "Ressource documentaire : {0} Mo",
      "en": "Document resource: {0} MB",
      "ru": "Размер документа: {0} МБ",
      "zh": "文档大小：{0} MB"
    }
  ],
  [
    "Pages du PDF : {0}",
    {
      "fr": "Pages du PDF : {0}",
      "en": "PDF pages: {0}",
      "ru": "Страниц PDF: {0}",
      "zh": "PDF 页数：{0}"
    }
  ],
  [
    "Pagination affichée par le lecteur : {0} ({1})",
    {
      "fr": "Pagination affichée par le lecteur : {0} ({1})",
      "en": "Pagination displayed by the reader: {0} ({1})",
      "ru": "Нумерация в читалке: {0} ({1})",
      "zh": "阅读器显示的页数：{0}（{1}）"
    }
  ],
  [
    "[RÉCUPÉRÉ] Arborescence PDF détachée validée : {0} pages, dont {1} dans la continuation.",
    {
      "fr": "[RÉCUPÉRÉ] Arborescence PDF détachée validée : {0} pages, dont {1} dans la continuation.",
      "en": "[RECOVERED] Detached PDF page tree validated: {0} pages, including {1} continuation pages.",
      "ru": "[ВОССТАНОВЛЕНО] Проверено дерево PDF: {0} страниц, включая {1} страниц продолжения.",
      "zh": "[已恢复] PDF 页面树已验证：{0} 页，其中 {1} 页来自后续部分。"
    }
  ],
  [
    "[INCOMPLET] Publication : {0}/{1} pages ({2} manquante(s))",
    {
      "fr": "[INCOMPLET] Publication : {0}/{1} pages ({2} manquante(s))",
      "en": "[INCOMPLETE] Publication: {0}/{1} pages ({2} missing)",
      "ru": "[НЕПОЛНО] Публикация: {0}/{1} страниц (отсутствует {2})",
      "zh": "[不完整] 文档：{0}/{1} 页（缺少 {2} 页）"
    }
  ],
  [
    "Aucun PDF sauvegardé : le lecteur n'a fourni qu'un aperçu incomplet.",
    {
      "fr": "Aucun PDF sauvegardé : le lecteur n'a fourni qu'un aperçu incomplet.",
      "en": "No PDF saved: the reader supplied an incomplete preview.",
      "ru": "PDF не сохранён: читалка предоставила неполный образец.",
      "zh": "未保存 PDF：阅读器仅提供了不完整的预览。"
    }
  ],
  [
    "Récupération PDF : réponse déjà chargée par le navigateur",
    {
      "fr": "Récupération PDF : réponse déjà chargée par le navigateur",
      "en": "PDF resource: reusing the browser response",
      "ru": "PDF: используется ответ браузера",
      "zh": "PDF：使用浏览器已加载的响应"
    }
  ],
  [
    "Ressource PDF : réponse déjà chargée par le navigateur",
    {
      "fr": "Ressource PDF : réponse déjà chargée par le navigateur",
      "en": "PDF resource: reusing the browser response",
      "ru": "PDF: используется ответ браузера",
      "zh": "PDF：使用浏览器已加载的响应"
    }
  ],
  [
    "Récupération PDF : le serveur a renvoyé le fichier complet",
    {
      "fr": "Récupération PDF : le serveur a renvoyé le fichier complet",
      "en": "PDF retrieval: the server returned the complete file",
      "ru": "Загрузка PDF: сервер вернул полный файл",
      "zh": "PDF 下载：服务器返回了完整文件"
    }
  ],
  [
    "Récupération PDF : segment {0}/{1} ({2}/{3} octets)",
    {
      "fr": "Récupération PDF : segment {0}/{1} ({2}/{3} octets)",
      "en": "PDF retrieval: segment {0}/{1} ({2}/{3} bytes)",
      "ru": "Загрузка PDF: сегмент {0}/{1} ({2}/{3} байт)",
      "zh": "PDF 下载：分段 {0}/{1}（{2}/{3} 字节）"
    }
  ],
  [
    "Récupération PDF {0}/2 échouée : {1}",
    {
      "fr": "Récupération PDF {0}/2 échouée : {1}",
      "en": "PDF retrieval {0}/2 failed: {1}",
      "ru": "Неудачная загрузка PDF {0}/2: {1}",
      "zh": "PDF 下载第 {0}/2 次失败：{1}"
    }
  ],
  [
    "Récupération EPUB {0}/2 échouée : {1}",
    {
      "fr": "Récupération EPUB {0}/2 échouée : {1}",
      "en": "EPUB retrieval {0}/2 failed: {1}",
      "ru": "Неудачная загрузка EPUB {0}/2: {1}",
      "zh": "EPUB 下载第 {0}/2 次失败：{1}"
    }
  ],
  [
    "Conversion demandée : rendu des pages PDF en PNG à 200 ppp pour produire {0}.",
    {
      "fr": "Conversion demandée : rendu des pages PDF en PNG à 200 ppp pour produire {0}.",
      "en": "Requested conversion: PDF pages rendered to PNG at 200 dpi for {0}.",
      "ru": "Конвертация: страницы PDF преобразуются в PNG при 200 dpi для {0}.",
      "zh": "转换：PDF 页面以 200 dpi 渲染为 PNG，生成 {0}。"
    }
  ],
  [
    "Conversion EPUB : impression des sections XHTML avec Chrome en conservant texte, images et mise en forme.",
    {
      "fr": "Conversion EPUB : impression des sections XHTML avec Chrome en conservant texte, images et mise en forme.",
      "en": "EPUB conversion: XHTML sections printed with Chrome, preserving text, images and layout.",
      "ru": "Конвертация EPUB: Chrome печатает разделы XHTML, сохраняя текст, изображения и оформление.",
      "zh": "EPUB 转换：使用 Chrome 打印 XHTML 部分，保留文字、图片和格式。"
    }
  ],
  [
    "Pages produites après mise en pages EPUB : {0}",
    {
      "fr": "Pages produites après mise en pages EPUB : {0}",
      "en": "Pages after EPUB layout: {0}",
      "ru": "Страниц после вёрстки EPUB: {0}",
      "zh": "EPUB 排版后页数：{0}"
    }
  ],
  [
    "Diagnostic EPUB : des entrées ZIP locales détachées existent et demandent une analyse supplémentaire.",
    {
      "fr": "Diagnostic EPUB : des entrées ZIP locales détachées existent et demandent une analyse supplémentaire.",
      "en": "EPUB diagnostic: detached local ZIP entries require further analysis.",
      "ru": "Диагностика EPUB: обнаружены отделённые записи ZIP; требуется дополнительный анализ.",
      "zh": "EPUB 诊断：发现分离的本地 ZIP 条目，需要进一步分析。"
    }
  ],
  [
    "Aucun fichier de lecture sauvegardé : la ressource EPUB reçue ne couvre pas tous les documents annoncés par sa propre table des matières.",
    {
      "fr": "Aucun fichier de lecture sauvegardé : la ressource EPUB reçue ne couvre pas tous les documents annoncés par sa propre table des matières.",
      "en": "No reading file saved: the EPUB does not contain every document listed in its table of contents.",
      "ru": "Файл не сохранён: EPUB содержит не все документы, указанные в оглавлении.",
      "zh": "未保存阅读文件：EPUB 未包含其目录中列出的所有文档。"
    }
  ],
  [
    "Compteur provisoire 1/1 ignoré après chargement des pages.",
    {
      "fr": "Compteur provisoire 1/1 ignoré après chargement des pages.",
      "en": "Provisional 1/1 counter ignored after pages loaded.",
      "ru": "Временный счётчик 1/1 проигнорирован после загрузки страниц.",
      "zh": "页面加载后忽略临时的 1/1 计数。"
    }
  ],
  [
    "CDN de pages autorisé automatiquement : {0} ({1}/{2} ressources sélectionnées)",
    {
      "fr": "CDN de pages autorisé automatiquement : {0} ({1}/{2} ressources sélectionnées)",
      "en": "Page CDN allowed automatically: {0} ({1}/{2} selected resources)",
      "ru": "CDN страниц разрешён автоматически: {0} ({1}/{2} ресурсов)",
      "zh": "已自动允许页面 CDN：{0}（{1}/{2} 个已选资源）"
    }
  ],
  [
    "Extraction incomplète : {0} page(s) manquante(s).",
    {
      "fr": "Extraction incomplète : {0} page(s) manquante(s).",
      "en": "Incomplete extraction: {0} missing page(s).",
      "ru": "Извлечение неполное: отсутствует {0} страниц.",
      "zh": "提取不完整：缺少 {0} 页。"
    }
  ],
  [
    "Détection incomplète : {0}/{1}. Corrigez --selector ou vérifiez la source.",
    {
      "fr": "Détection incomplète : {0}/{1}. Corrigez --selector ou vérifiez la source.",
      "en": "Incomplete detection: {0}/{1}. Adjust --selector or check the source.",
      "ru": "Обнаружение неполное: {0}/{1}. Уточните --selector или проверьте источник.",
      "zh": "检测不完整：{0}/{1}。请调整 --selector 或检查来源。"
    }
  ],
  [
    "[RÉCUPÉRATION REFUSÉE] {0}",
    {
      "fr": "[RÉCUPÉRATION REFUSÉE] {0}",
      "en": "[RECOVERY REFUSED] {0}",
      "ru": "[ВОССТАНОВЛЕНИЕ ОТКЛОНЕНО] {0}",
      "zh": "[恢复被拒绝] {0}"
    }
  ],
  [
    "[ÉCHEC] {0} : {1}",
    {
      "fr": "[ÉCHEC] {0} : {1}",
      "en": "[FAILED] {0}: {1}",
      "ru": "[ОШИБКА] {0}: {1}",
      "zh": "[失败] {0}：{1}"
    }
  ],
  [
    "Récupération SSL : initialisation sécurisée du domaine...",
    {
      "fr": "Récupération SSL : initialisation sécurisée du domaine...",
      "en": "SSL recovery: initializing the domain securely...",
      "ru": "Восстановление SSL: безопасная инициализация домена...",
      "zh": "SSL 恢复：安全初始化域名…"
    }
  ],
  [
    "Récupération SSL réussie.",
    {
      "fr": "Récupération SSL réussie.",
      "en": "SSL recovery succeeded.",
      "ru": "SSL успешно восстановлен.",
      "zh": "SSL 恢复成功。"
    }
  ],
  [
    "Récupération SSL échouée : {0}",
    {
      "fr": "Récupération SSL échouée : {0}",
      "en": "SSL recovery failed: {0}",
      "ru": "Восстановление SSL не удалось: {0}",
      "zh": "SSL 恢复失败：{0}"
    }
  ],
  [
    "Impossible d'ouvrir le document après {0} tentative(s).",
    {
      "fr": "Impossible d'ouvrir le document après {0} tentative(s).",
      "en": "Could not open the document after {0} attempt(s).",
      "ru": "Не удалось открыть документ после {0} попыток.",
      "zh": "尝试 {0} 次后仍无法打开文档。"
    }
  ],
  [
    "Chrome introuvable : {0}",
    {
      "fr": "Chrome introuvable : {0}",
      "en": "Chrome not found: {0}",
      "ru": "Chrome не найден: {0}",
      "zh": "找不到 Chrome：{0}"
    }
  ],
  [
    "Ressource PDF inaccessible : HTTP {0}",
    {
      "fr": "Ressource PDF inaccessible : HTTP {0}",
      "en": "PDF resource unavailable: HTTP {0}",
      "ru": "PDF недоступен: HTTP {0}",
      "zh": "PDF 文件无法访问：HTTP {0}"
    }
  ],
  [
    "Ressource EPUB inaccessible : HTTP {0}",
    {
      "fr": "Ressource EPUB inaccessible : HTTP {0}",
      "en": "EPUB resource unavailable: HTTP {0}",
      "ru": "EPUB недоступен: HTTP {0}",
      "zh": "EPUB 文件无法访问：HTTP {0}"
    }
  ],
  [
    "La ressource documentaire détectée n'est pas un PDF valide.",
    {
      "fr": "La ressource documentaire détectée n'est pas un PDF valide.",
      "en": "The detected document is not a valid PDF.",
      "ru": "Обнаруженный документ не является корректным PDF.",
      "zh": "检测到的文档不是有效的 PDF。"
    }
  ],
  [
    "Le lecteur a renvoyé un PDF vide ou invalide.",
    {
      "fr": "Le lecteur a renvoyé un PDF vide ou invalide.",
      "en": "The reader returned an empty or invalid PDF.",
      "ru": "Читалка вернула пустой или некорректный PDF.",
      "zh": "阅读器返回了空的或无效的 PDF。"
    }
  ],
  [
    "La ressource PDF détectée ne contient aucune page.",
    {
      "fr": "La ressource PDF détectée ne contient aucune page.",
      "en": "The detected PDF contains no pages.",
      "ru": "Обнаруженный PDF не содержит страниц.",
      "zh": "检测到的 PDF 没有任何页面。"
    }
  ],
  [
    "La ressource PDF détectée ne peut pas être validée : {0}",
    {
      "fr": "La ressource PDF détectée ne peut pas être validée : {0}",
      "en": "The detected PDF cannot be validated: {0}",
      "ru": "Не удалось проверить PDF: {0}",
      "zh": "无法验证 PDF 文件：{0}"
    }
  ],
  [
    "La ressource EPUB détectée est invalide : {0}",
    {
      "fr": "La ressource EPUB détectée est invalide : {0}",
      "en": "The detected EPUB is invalid: {0}",
      "ru": "Обнаруженный EPUB некорректен: {0}",
      "zh": "检测到的 EPUB 无效：{0}"
    }
  ],
  [
    "Arborescence PDF complète vérifiée. La reconstruire pour ce document que vous possédez ou êtes autorisé à tester ? [o/N] ",
    {
      "fr": "Arborescence PDF complète vérifiée. La reconstruire pour ce document que vous possédez ou êtes autorisé à tester ? [o/N] ",
      "en": "Complete PDF page tree verified. Rebuild it for this document you own or are authorized to test? [y/N] ",
      "ru": "Полное дерево PDF проверено. Восстановить документ, которым вы владеете или имеете право тестировать? [y/N] ",
      "zh": "完整 PDF 页面树已验证。是否为您拥有或获准测试的文档重建页面树？[y/N] "
    }
  ],
  [
    "Chrome executable found",
    {
      "fr": "Exécutable Chrome trouvé",
      "en": "Chrome executable found",
      "ru": "Исполняемый файл Chrome найден",
      "zh": "已找到 Chrome 程序"
    }
  ],
  [
    "Chrome executable is missing",
    {
      "fr": "Exécutable Chrome absent",
      "en": "Chrome executable is missing",
      "ru": "Исполняемый файл Chrome отсутствует",
      "zh": "找不到 Chrome 程序"
    }
  ],
  [
    "output root is ready",
    {
      "fr": "Dossier de sortie prêt",
      "en": "output root is ready",
      "ru": "Каталог результатов готов",
      "zh": "输出目录已就绪"
    }
  ],
  [
    "output root can be created",
    {
      "fr": "Dossier de sortie créable",
      "en": "output root can be created",
      "ru": "Каталог результатов можно создать",
      "zh": "可以创建输出目录"
    }
  ],
  [
    "output root is not a directory",
    {
      "fr": "La sortie n'est pas un dossier",
      "en": "output root is not a directory",
      "ru": "Путь результатов не является каталогом",
      "zh": "输出路径不是目录"
    }
  ],
  [
    "output root cannot be created or written",
    {
      "fr": "Dossier de sortie inaccessible en écriture",
      "en": "output root cannot be created or written",
      "ru": "Нельзя создать каталог результатов или записать в него",
      "zh": "无法创建或写入输出目录"
    }
  ],
  [
    "optional conversion support inspected",
    {
      "fr": "Prise en charge des conversions vérifiée",
      "en": "optional conversion support inspected",
      "ru": "Поддержка конвертации проверена",
      "zh": "已检查转换支持"
    }
  ],
  [
    "no third-party source manifest installed",
    {
      "fr": "Aucun manifeste de source tiers installé",
      "en": "no third-party source manifest installed",
      "ru": "Сторонние источники не установлены",
      "zh": "未安装第三方来源清单"
    }
  ],
  [
    "schema version {0} is compatible",
    {
      "fr": "Schéma version {0} compatible",
      "en": "schema version {0} is compatible",
      "ru": "Схема версии {0} совместима",
      "zh": "架构版本 {0} 兼容"
    }
  ],
  [
    "schema version {0} will migrate to {1} when opened",
    {
      "fr": "Schéma {0} migré vers {1} à l'ouverture",
      "en": "schema version {0} will migrate to {1} when opened",
      "ru": "Схема {0} будет обновлена до {1} при открытии",
      "zh": "打开时架构 {0} 将迁移至 {1}"
    }
  ],
  [
    "incompatible schema version {0}; expected {1}",
    {
      "fr": "Schéma {0} incompatible ; version attendue : {1}",
      "en": "incompatible schema version {0}; expected {1}",
      "ru": "Несовместимая схема {0}; требуется {1}",
      "zh": "架构 {0} 不兼容；需要 {1}"
    }
  ],
  [
    "required dependency {0} is installed",
    {
      "fr": "Dépendance requise {0} installée",
      "en": "required dependency {0} is installed",
      "ru": "Обязательная зависимость {0} установлена",
      "zh": "已安装必需依赖 {0}"
    }
  ],
  [
    "required dependency {0} is missing",
    {
      "fr": "Dépendance requise {0} absente",
      "en": "required dependency {0} is missing",
      "ru": "Обязательная зависимость {0} отсутствует",
      "zh": "缺少必需依赖 {0}"
    }
  ],
  [
    "library index is absent and reconstructible",
    {
      "fr": "Index absent, reconstructible",
      "en": "library index is absent and reconstructible",
      "ru": "Индекс отсутствует, его можно восстановить",
      "zh": "索引不存在，可以重建"
    }
  ],
  [
    "library state is not initialized yet",
    {
      "fr": "État de bibliothèque non initialisé",
      "en": "library state is not initialized yet",
      "ru": "Состояние библиотеки ещё не создано",
      "zh": "尚未初始化书库状态"
    }
  ],
  [
    "job queue is not initialized yet",
    {
      "fr": "File d'attente non initialisée",
      "en": "job queue is not initialized yet",
      "ru": "Очередь ещё не создана",
      "zh": "尚未初始化任务队列"
    }
  ],
  [
    "SQLite file is unreadable",
    {
      "fr": "Fichier SQLite illisible",
      "en": "SQLite file is unreadable",
      "ru": "Файл SQLite нечитаем",
      "zh": "无法读取 SQLite 文件"
    }
  ]
]

_MESSAGES.extend([["Diagnostic PDF : les {0} pages visibles correspondent au préfixe d'une arborescence détachée ordonnée de {1} pages. Sa continuation contient {2} objet(s) /Page, dont {3} avec contenu et {4} avec ressources.",{"fr":"Diagnostic PDF : les {0} pages visibles correspondent au préfixe d'une arborescence détachée ordonnée de {1} pages. Sa continuation contient {2} objet(s) /Page, dont {3} avec contenu et {4} avec ressources.","en":"PDF diagnostic: the {0} visible pages match the prefix of a detached ordered tree of {1} pages. Its continuation contains {2} /Page objects, {3} with content and {4} with resources.","ru":"Диагностика PDF: {0} видимых страниц совпадают с началом отделённого дерева из {1} страниц. Продолжение: {2} объектов /Page, {3} с содержимым и {4} с ресурсами.","zh":"PDF 诊断：{0} 个可见页面与分离页面树的前缀匹配，该树共 {1} 页。后续包含 {2} 个 /Page 对象，其中 {3} 个有内容，{4} 个有资源。"}],["Diagnostic PDF : arborescence(s) de pages détachée(s) déclarant {0} page(s); elles ne font pas partie du document lisible.",{"fr":"Diagnostic PDF : arborescence(s) de pages détachée(s) déclarant {0} page(s); elles ne font pas partie du document lisible.","en":"PDF diagnostic: detached trees declare {0} pages; they are outside the readable document.","ru":"Диагностика PDF: отделённые деревья заявляют {0} страниц; они не входят в читаемый документ.","zh":"PDF 诊断：分离页面树声明了 {0} 页；这些页面不属于可读文档。"}],["Effectuez la connexion ou la validation dans Chrome, puis appuyez sur Entrée...",{"fr":"Effectuez la connexion ou la validation dans Chrome, puis appuyez sur Entrée...","en":"Complete login or verification in Chrome, then press Enter...","ru":"Завершите вход или проверку в Chrome и нажмите Enter...","zh":"请在 Chrome 中完成登录或验证，然后按回车…"}],["Vérification du site détectée dans Chrome. Terminez-la si le site demande une action, puis appuyez sur Entrée...",{"fr":"Vérification du site détectée dans Chrome. Terminez-la si le site demande une action, puis appuyez sur Entrée...","en":"Site verification detected in Chrome. Complete the requested action, then press Enter...","ru":"В Chrome обнаружена проверка сайта. Выполните её и нажмите Enter...","zh":"Chrome 检测到网站验证。请完成网站要求的操作，然后按回车…"}],["La vérification du site est toujours active. Relancez avec --wait-for-user et terminez-la dans Chrome avant de continuer.",{"fr":"La vérification du site est toujours active. Relancez avec --wait-for-user et terminez-la dans Chrome avant de continuer.","en":"Site verification is still active. Run with --wait-for-user and complete it in Chrome.","ru":"Проверка сайта ещё активна. Запустите с --wait-for-user и завершите её в Chrome.","zh":"网站验证仍然有效。请使用 --wait-for-user 重新运行并在 Chrome 中完成验证。"}],["PDF assemblé incomplet : {0}/{1} octets.",{"fr":"PDF assemblé incomplet : {0}/{1} octets.","en":"Assembled PDF incomplete: {0}/{1} bytes.","ru":"Собранный PDF неполон: {0}/{1} байт.","zh":"组装的 PDF 不完整：{0}/{1} 字节。"}],["compteur visible: {0}",{"fr":"compteur visible: {0}","en":"visible counter: {0}","ru":"видимый счётчик: {0}","zh":"可见计数：{0}"}],["conteneurs Scribd outer_page_N consécutifs",{"fr":"conteneurs Scribd outer_page_N consécutifs","en":"consecutive Scribd outer_page_N containers","ru":"последовательные контейнеры Scribd outer_page_N","zh":"连续的 Scribd outer_page_N 容器"}],["La ressource PDF n'a pas pu être récupérée après deux tentatives : {0}",{"fr":"La ressource PDF n'a pas pu être récupérée après deux tentatives : {0}","en":"Could not retrieve the PDF after two attempts: {0}","ru":"Не удалось загрузить PDF после двух попыток: {0}","zh":"尝试两次后无法获取 PDF：{0}"}],["La ressource EPUB n'a pas pu être récupérée après deux tentatives : {0}",{"fr":"La ressource EPUB n'a pas pu être récupérée après deux tentatives : {0}","en":"Could not retrieve the EPUB after two attempts: {0}","ru":"Не удалось загрузить EPUB после двух попыток: {0}","zh":"尝试两次后无法获取 EPUB：{0}"}],["Échec du segment PDF {0}-{1} après deux tentatives : {2}",{"fr":"Échec du segment PDF {0}-{1} après deux tentatives : {2}","en":"PDF segment {0}-{1} failed after two attempts: {2}","ru":"Сегмент PDF {0}-{1} не загружен после двух попыток: {2}","zh":"尝试两次后 PDF 分段 {0}-{1} 失败：{2}"}]])


_MESSAGES.extend([
  [
    "[OK] page {0}/{1} ({2} Ko)",
    {
      "fr": "[OK] page {0}/{1} ({2} Ko)",
      "en": "[OK] page {0}/{1} ({2} KB)",
      "ru": "[OK] страница {0}/{1} ({2} КБ)",
      "zh": "[OK] 第 {0}/{1} 页（{2} KB）"
    }
  ],
  [
    "[OK] page {0}/{1} ({2} Ko, navigateur)",
    {
      "fr": "[OK] page {0}/{1} ({2} Ko, navigateur)",
      "en": "[OK] page {0}/{1} ({2} KB, browser)",
      "ru": "[OK] страница {0}/{1} ({2} КБ, браузер)",
      "zh": "[OK] 第 {0}/{1} 页（{2} KB，浏览器）"
    }
  ],
  [
    "[DÉJÀ PRÉSENTE] page {0}/{1} ({2})",
    {
      "fr": "[DÉJÀ PRÉSENTE] page {0}/{1} ({2})",
      "en": "[ALREADY PRESENT] page {0}/{1} ({2})",
      "ru": "[УЖЕ ЕСТЬ] страница {0}/{1} ({2})",
      "zh": "[已存在] 第 {0}/{1} 页（{2}）"
    }
  ],
  [
    "[BLOQUÉ] page {0}: domaine non autorisé",
    {
      "fr": "[BLOQUÉ] page {0}: domaine non autorisé",
      "en": "[BLOCKED] page {0}: domain not allowed",
      "ru": "[ЗАБЛОКИРОВАНО] страница {0}: домен не разрешён",
      "zh": "[已阻止] 第 {0} 页：域名未经允许"
    }
  ],
  [
    "Téléchargement parallèle : {0} connexion(s), {1} ressource(s)",
    {
      "fr": "Téléchargement parallèle : {0} connexion(s), {1} ressource(s)",
      "en": "Parallel download: {0} connection(s), {1} resource(s)",
      "ru": "Параллельная загрузка: {0} соединений, {1} ресурсов",
      "zh": "并行下载：{0} 个连接，{1} 个资源"
    }
  ],
  [
    "Repli navigateur : {0} ressource(s) refusée(s) en téléchargement direct",
    {
      "fr": "Repli navigateur : {0} ressource(s) refusée(s) en téléchargement direct",
      "en": "Browser fallback: {0} resource(s) rejected by direct download",
      "ru": "Загрузка через браузер: прямой доступ к {0} ресурсам отклонён",
      "zh": "浏览器回退：直接下载被拒绝的 {0} 个资源"
    }
  ],
  [
    "[ESSAI {0}/{1}] page {2}: {3}",
    {
      "fr": "[ESSAI {0}/{1}] page {2}: {3}",
      "en": "[ATTEMPT {0}/{1}] page {2}: {3}",
      "ru": "[ПОПЫТКА {0}/{1}] страница {2}: {3}",
      "zh": "[尝试 {0}/{1}] 第 {2} 页：{3}"
    }
  ],
  [
    "Lecteur local : {0}",
    {
      "fr": "Lecteur local : {0}",
      "en": "Local reader: {0}",
      "ru": "Локальная читалка: {0}",
      "zh": "本地阅读器：{0}"
    }
  ],
  [
    "La progression est enregistrée automatiquement. Ctrl+C arrête le lecteur.",
    {
      "fr": "La progression est enregistrée automatiquement. Ctrl+C arrête le lecteur.",
      "en": "Reading progress is saved automatically. Ctrl+C stops the reader.",
      "ru": "Прогресс сохраняется автоматически. Ctrl+C останавливает читалку.",
      "zh": "阅读进度将自动保存。按 Ctrl+C 停止阅读器。"
    }
  ],
  [
    "Lecteur arrêté.",
    {
      "fr": "Lecteur arrêté.",
      "en": "Reader stopped.",
      "ru": "Читалка остановлена.",
      "zh": "阅读器已停止。"
    }
  ]
])


_MESSAGES.extend([
  [
    "Scribd demande de regarder une publicité pour libérer les pages. Terminez cette étape dans Chrome, puis appuyez sur Entrée ici...",
    {
      "fr": "Scribd demande de regarder une publicité pour libérer les pages. Terminez cette étape dans Chrome, puis appuyez sur Entrée ici...",
      "en": "Scribd asks you to watch an advertisement to unlock pages. Complete this step in Chrome, then press Enter here...",
      "ru": "Scribd просит просмотреть рекламу для открытия страниц. Завершите этот шаг в Chrome и нажмите Enter...",
      "zh": "Scribd 要求观看广告以解锁页面。请在 Chrome 中完成此步骤，然后在此按回车…"
    }
  ],
  [
    "KomaForge n'a pas pu vérifier l'état d'accès du lecteur Scribd; la capture est arrêtée pour éviter un faux succès.",
    {
      "fr": "KomaForge n'a pas pu vérifier l'état d'accès du lecteur Scribd; la capture est arrêtée pour éviter un faux succès.",
      "en": "KomaForge could not verify Scribd access; capture stopped to avoid reporting a false success.",
      "ru": "Не удалось проверить доступ Scribd; захват остановлен, чтобы избежать ложного результата.",
      "zh": "无法验证 Scribd 的访问状态；已停止截图，以免错误报告成功。"
    }
  ],
  [
    "Scribd a renvoyé un état d'accès illisible; la capture est arrêtée pour éviter un faux succès.",
    {
      "fr": "Scribd a renvoyé un état d'accès illisible; la capture est arrêtée pour éviter un faux succès.",
      "en": "Scribd returned an unreadable access state; capture stopped to avoid reporting a false success.",
      "ru": "Scribd вернул нечитаемое состояние доступа; захват остановлен во избежание ложного результата.",
      "zh": "Scribd 返回了无法读取的访问状态；已停止截图，以免错误报告成功。"
    }
  ],
  [
    "Scribd a reconnu le document, mais aucune page outer_page_N n'est disponible dans le lecteur.",
    {
      "fr": "Scribd a reconnu le document, mais aucune page outer_page_N n'est disponible dans le lecteur.",
      "en": "Scribd recognized the document, but no outer_page_N page is available in the reader.",
      "ru": "Документ Scribd распознан, но в читалке нет страниц outer_page_N.",
      "zh": "已识别 Scribd 文档，但阅读器中没有可用的 outer_page_N 页面。"
    }
  ],
  [
    "Scribd expose du texte DOM, mais la page rendue {0} reste visuellement vide. KomaForge refuse d'annoncer cette publication comme complète.",
    {
      "fr": "Scribd expose du texte DOM, mais la page rendue {0} reste visuellement vide. KomaForge refuse d'annoncer cette publication comme complète.",
      "en": "Scribd exposes DOM text, but rendered page {0} remains visually blank. KomaForge refuses to report this publication as complete.",
      "ru": "Scribd предоставляет текст DOM, но страница {0} визуально пуста. KomaForge не считает публикацию полной.",
      "zh": "Scribd 提供了 DOM 文本，但渲染后的第 {0} 页仍为空白。KomaForge 不会将此出版物标记为完整。"
    }
  ],
  [
    "L'état d'accès Scribd a changé deux fois pendant la capture de la page {0}; relancez l'extraction.",
    {
      "fr": "L'état d'accès Scribd a changé deux fois pendant la capture de la page {0}; relancez l'extraction.",
      "en": "Scribd access changed twice while capturing page {0}; restart extraction.",
      "ru": "Доступ Scribd дважды изменился при захвате страницы {0}; запустите извлечение заново.",
      "zh": "在截取第 {0} 页期间，Scribd 的访问状态改变了两次；请重新运行提取。"
    }
  ],
  [
    "Scribd n'a pas produit une image PNG valide pour la page {0}.",
    {
      "fr": "Scribd n'a pas produit une image PNG valide pour la page {0}.",
      "en": "Scribd did not produce a valid PNG for page {0}.",
      "ru": "Scribd не создал корректный PNG для страницы {0}.",
      "zh": "Scribd 未为第 {0} 页生成有效的 PNG 图片。"
    }
  ],
  [
    "Scribd limite temporairement l'accès ({0}). La publicité de déverrouillage ne s'est pas chargée ou n'a pas été terminée. KomaForge refuse d'archiver le panneau flouté comme une page réussie. Relancez avec --wait-for-user, puis terminez le déverrouillage officiel dans Chrome; un bloqueur de publicités ou un VPN filtrant peut empêcher ce parcours.",
    {
      "fr": "Scribd limite temporairement l'accès ({0}). La publicité de déverrouillage ne s'est pas chargée ou n'a pas été terminée. KomaForge refuse d'archiver le panneau flouté comme une page réussie. Relancez avec --wait-for-user, puis terminez le déverrouillage officiel dans Chrome; un bloqueur de publicités ou un VPN filtrant peut empêcher ce parcours.",
      "en": "Scribd temporarily limits access ({0}). The unlocking advertisement did not load or was not completed. KomaForge refuses to archive a blurred panel as a successful page. Restart with --wait-for-user and complete the official unlocking step in Chrome; ad blockers or a filtering VPN may prevent this workflow.",
      "ru": "Scribd временно ограничивает доступ ({0}). Реклама для открытия страниц не загрузилась или не завершена. Размытая панель не считается страницей. Запустите с --wait-for-user и завершите официальный шаг в Chrome; блокировщик рекламы или VPN с фильтрацией могут мешать.",
      "zh": "Scribd 暂时限制访问（{0}）。解锁广告未加载或尚未完成。KomaForge 不会将模糊面板当作成功页面保存。请使用 --wait-for-user 重新运行，并在 Chrome 中完成官方解锁步骤；广告拦截器或过滤型 VPN 可能会阻止此流程。"
    }
  ]
])


_MESSAGES.extend([
  [
    "Section XHTML EPUB invalide : {0}. La conversion est arrêtée pour éviter d'imprimer une page d'erreur.",
    {
      "fr": "Section XHTML EPUB invalide : {0}. La conversion est arrêtée pour éviter d'imprimer une page d'erreur.",
      "en": "Invalid EPUB XHTML section: {0}. Conversion stopped to avoid printing an error page.",
      "ru": "Некорректный раздел XHTML EPUB: {0}. Конвертация остановлена, чтобы не печатать страницу ошибки.",
      "zh": "EPUB XHTML 章节无效：{0}。已停止转换，以免打印错误页面。"
    }
  ]
])


def set_diagnostic_language(language: str) -> None:
    _LANGUAGE.set(language if language in {"fr", "en", "ru", "zh"} else "fr")


def localize_diagnostic(message: str, language: str | None = None) -> str:
    language = language or _LANGUAGE.get()
    for source, translations in _MESSAGES:
        pattern = re.sub(r"\\\{[0-9]+\\\}", "(.*?)", re.escape(source))
        match = re.fullmatch(pattern, message, flags=re.DOTALL)
        if match:
            return translations.get(language, source).format(*match.groups())
    return message


def diagnostic_print(*values, **options) -> None:
    builtins.print(*(
        localize_diagnostic(value) if isinstance(value, str) else value
        for value in values
    ), **options)


def diagnostic_input(prompt: str = "") -> str:
    return builtins.input(localize_diagnostic(prompt))
