"""Platform-specific routes from verified public pages; no I/O or tool invocation."""

_ROUTES = {
    'Tencent News': (
        '有预读候选时先在详情核对媒体与发布时间、立即回传；再用当前可用浏览器打开配置主页补扫。'
        '没有预读时直接打开配置主页，核对身份并进入已有“图文/文章”栏目（om_article）；'
        '等待列表渲染后读取文章链接与同条发布时间。静态 HTML 可能只有空壳，不能据此认定零篇。'
        '只按页面已有翻页/加载更多继续至窗口旧边界；详情发布时间优先，互动/评论时间不能代替。'
        '若浏览器不可用或页面被登录/验证码阻挡，保留已核实结果并说明阻挡，不换账号或绕过限制。'
    ),
    'NetEase': (
        '先读取配置主页的原始 HTML；在同一个 li.js-item.item 中配对 h4 a.title 的链接与 span.time，'
        '核对主页账号身份，再打开窗口内文章核验原始发布时间。日期不足或冲突时以文章原始发布标记核实，'
        '不能用推荐栏、转载刷新时间或相邻文章时间。仅当 HTML 无列表时使用当前可用浏览器渲染同一入口。'
    ),
    'Official Elsewhere': (
        '配置的 /zh/articles 是多创作者混合列表，先匹配本次账号的可见作者名称，再点击该作者链接。'
        '已核实 elsewhere别处发生 的站内作者页为 /zh/elsewhere；仅通过页面当前可见的匹配链接导航，'
        '不得为其他账号套用或自行拼接地址。只收该作者文章，列表 time 仅作日期线索；'
        '详情核验 article:author 与 article:published_time 或 JSON-LD datePublished，换算北京时间，'
        '不能取 dateModified。最新同源文章已早于窗口时可记录有证据的零篇，不把其他创作者文章补入。'
    ),
    'Official Jiqizhixin': (
        '只打开配置入口。若显示“机器之心·数据服务”或“还在费劲爬数据”等服务提示而无新闻列表，'
        '记录 source_status=failed、note=list_blocked 并停止此源，不把 HTTP 200 当列表可用。'
        '不绕过限制，不自行改为付费 RSS/API、ScienceAI 或同名跨平台账号；需要新的可读入口时交由用户选择。'
        '若实际正常显示新闻列表，核对机器之心原文身份与发布时间；作者缺失可为 null，不据此拒收。'
    ),
}


def render_source_guidance(sources):
    """Render one bounded route per platform actually present in this task."""
    platforms = list(dict.fromkeys(source.get('platform') for source in sources))
    routes = [f'- {platform}：{_ROUTES[platform]}' for platform in platforms if platform in _ROUTES]
    if not routes:
        return ''
    return '\n'.join([
        '按本次配置平台使用以下路线，账号和主页以本次来源表为准；不新增账号、不替换平台。',
        '优先使用当前任务已可用的网页/浏览器能力；缺少能力时只做一次针对性工具发现，仍不可用则说明失败。'
        '不要反复枚举工具，也不要猜测工具函数名或未观察到的接口。',
        *routes,
    ])
