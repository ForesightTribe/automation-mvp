"""Downloading a report — the same numbers, as an .xlsx.

⚠️ Every figure here comes from `reports_service`, the code that already feeds
the screen. Nothing in this module queries the database or does arithmetic of its
own, so a downloaded file cannot disagree with the table it was downloaded from.
That is the entire design constraint: a report the client forwards has to be the
report they looked at.

It exports what is SELECTED, not everything available. The sales pivot carries a
daily and a weekly axis and the page shows one at a time; the file follows the
page. Exporting both would be a different document from the one on screen.
"""
import uuid
from datetime import date
from tempfile import mkdtemp

from sqlalchemy.ext.asyncio import AsyncSession

from exports.workbook import write_workbook
from app.schemas.exports import Column, Report, Section
from app.services import reports_service

MONEY = "money"


def _sales_daily(pivot) -> Section:
    """SKU rows under their category, a column per day, subtotals and a grand total."""
    money = pivot.metric == "value"
    kind = MONEY if money else "count"
    columns = [
        # Blank means "same category as above", the way a pivot prints it.
        Column(key="category", header="Category", type="text", blank_empty=True),
        Column(key="sku", header="SKU Name", type="text", width=44, blank_empty=True),
        *[
            Column(key=f"d{i}", header=d.date.strftime("%d %b"), type=kind, emphasis="bar")
            for i, d in enumerate(pivot.days)
        ],
        Column(key="total", header="Total", type=kind),
    ]

    rows: list[dict] = []
    for platform in pivot.platforms:
        for cat in platform.categories:
            first = len(rows)
            for sku in cat.skus:
                rows.append(
                    {"category": None, "sku": sku.name, "is_total": False,
                     **{f"d{i}": v for i, v in enumerate(sku.cells)}, "total": sku.total}
                )
            if len(rows) > first:
                rows[first]["category"] = cat.name
            rows.append(
                {"category": f"{cat.name} Total", "sku": None, "is_total": True,
                 **{f"d{i}": v for i, v in enumerate(cat.cells)}, "total": cat.total}
            )

    total = pivot.platforms[0] if len(pivot.platforms) == 1 else None
    grand = (
        {"category": "Grand Total", "sku": None, "is_total": True,
         **{f"d{i}": v for i, v in enumerate(total.cells)}, "total": total.total}
        if total
        else None
    )
    return Section(
        key="sales_daily",
        title="Sales by Category and SKU",
        description=f"{'Revenue' if money else 'Units'} per SKU per day, grouped by category.",
        context=f"{pivot.start:%d %b} to {pivot.end:%d %b %Y} · {len(pivot.days)} days",
        columns=columns,
        rows=rows,
        total_row=grand,
        highlight_key="is_total",
        notes=["Weekend columns on screen are Fri to Sun, the client's convention."],
    )


def _sales_weekly(pivot) -> Section:
    """The weekday/weekend split, per complete Mon–Sun week.

    ⚠️ Every figure is an AVERAGE PER DAY, not a sum, because Mon–Thu is four days
    and Fri–Sun is three: summed halves are not comparable quantities. The header
    says so, since a column of numbers gives no clue either way.
    """
    kind = MONEY if pivot.metric == "value" else "count"
    columns = [
        Column(key="category", header="Category", type="text", blank_empty=True),
        Column(key="sku", header="SKU Name", type="text", width=44, blank_empty=True),
        Column(key="half", header="Half", type="text"),
        *[Column(key=f"w{i}", header=w.label, type=kind) for i, w in enumerate(pivot.weeks)],
        Column(key="total", header="Avg day", type=kind),
    ]

    rows: list[dict] = []

    def _pair(label_cat, label_sku, node, is_total):
        for half, split in (("Mon–Thu", node.weekday), ("Fri–Sun", node.weekend)):
            rows.append(
                {"category": label_cat if half == "Mon–Thu" else None,
                 "sku": label_sku if half == "Mon–Thu" else None,
                 "half": half, "is_total": is_total,
                 **{f"w{i}": v for i, v in enumerate(split.cells)}, "total": split.total}
            )

    for platform in pivot.platforms:
        for cat in platform.categories:
            for sku in cat.skus:
                _pair(None, sku.name, sku, False)
            rows[-2]["category"] = None
            _pair(f"{cat.name} Total", None, cat, True)

    total = pivot.platforms[0] if len(pivot.platforms) == 1 else None
    return Section(
        key="sales_weekly",
        title="Weekday and Weekend Planning",
        description="Average day in each half of the week, per complete Monday to Sunday week.",
        context=f"{len(pivot.weeks)} complete weeks · every figure is an average per day",
        columns=columns,
        rows=rows,
        total_row=(
            {"category": "Grand Total", "sku": None, "half": "All 7 days", "is_total": True,
             **{f"w{i}": None for i in range(len(pivot.weeks))}, "total": total.week_total}
            if total
            else None
        ),
        highlight_key="is_total",
        notes=[
            "Mon–Thu is four days and Fri–Sun is three, so the halves are reported as "
            "averages per day. Summing them would compare unlike quantities.",
            "Only complete Monday to Sunday weeks inside the window are included; a partial "
            "week at either edge is left out rather than counted short.",
        ],
    )


def _weekend(report) -> list[Section]:
    """The client's weekend planning workbook: three sheets built from one query.

    Sheet 1 is the planning table — campaigns down, weekends across, with an
    all-weekend Grand Total group and Max Spends, the highest average day of
    spend each campaign reached in any single weekend. That last column is the
    reason the sheet exists: it is the ceiling a campaign has demonstrated,
    rather than a budget someone hopes it will use.

    Sheet 2 is the weekday baseline a weekend push is judged against. Sheet 3 is
    banners, which carry no revenue attribution and are therefore judged on cost
    per thousand impressions instead of RoAS.
    """
    money = MONEY
    planning_cols = [
        Column(key="ad_type", header="Ad Type", type="text", blank_empty=True),
        Column(key="name", header="Campaign Name", type="text", width=44),
    ]
    for i, w in enumerate(report.weekends):
        planning_cols += [
            Column(key=f"s{i}", header=f"{w.label} · Spends", type=money, emphasis="bar"),
            Column(key=f"r{i}", header=f"{w.label} · Revenue", type=money, emphasis="bar"),
            Column(key=f"o{i}", header=f"{w.label} · ROAS", type="rating"),
        ]
    planning_cols += [
        Column(key="gt_spend", header="Grand Total · Spends", type=money),
        Column(key="gt_revenue", header="Grand Total · Revenue", type=money),
        Column(key="gt_roas", header="Grand Total · ROAS", type="rating"),
        Column(
            key="max_daily",
            header="Max Spends",
            type=money,
            emphasis="bar",
            help=(
                "The highest average day of spend this campaign reached in any single "
                "weekend — the ceiling it has actually demonstrated, not a target."
            ),
        ),
    ]

    def _cells(c) -> dict:
        out = {}
        for i, half in enumerate(c.weekends):
            out[f"s{i}"], out[f"r{i}"], out[f"o{i}"] = half.spend, half.revenue, half.roas
        out["gt_spend"] = c.weekend_total.spend
        out["gt_revenue"] = c.weekend_total.revenue
        out["gt_roas"] = c.weekend_total.roas
        out["max_daily"] = c.max_daily_spend
        return out

    rows: list[dict] = []
    for sec in report.sections:
        for i, c in enumerate(sec.campaigns):
            # The block name prints once, at its first row, as in their sheet.
            rows.append(
                {"ad_type": sec.label if i == 0 else None, "name": c.name,
                 "is_total": False, **_cells(c)}
            )
        rows.append(
            {"ad_type": None, "name": sec.subtotal.name, "is_total": True, **_cells(sec.subtotal)}
        )

    planning = Section(
        key="weekend_planning",
        title="Weekend Planning",
        description="Spend, revenue and ROAS per campaign, one column group per weekend.",
        context=(
            f"{report.start:%d %b} to {report.end:%d %b %Y} · "
            f"{len(report.weekends)} weekends · Fri to Sun"
        ),
        columns=planning_cols,
        rows=rows,
        total_row={"ad_type": "Grand Total", "name": None, "is_total": True, **_cells(report.totals)},
        highlight_key="is_total",
        notes=[
            "A weekend is Friday to Sunday, the same definition the sales report uses.",
            "ROAS is revenue divided by spend, recomputed from the sums rather than averaged.",
            "Max Spends divides a weekend's spend by the days of it inside the selected "
            "window, so a weekend clipped by the date picker is not scored as if it were short.",
            "Banner campaigns are on their own sheet: they carry no revenue attribution, so "
            "they would sit here as permanent zero-ROAS rows.",
        ],
    )

    weekday = Section(
        key="weekday_performance",
        title="Weekday Performance",
        description="The same campaigns Monday to Thursday, the baseline a weekend push is judged against.",
        context=f"{report.start:%d %b} to {report.end:%d %b %Y} · Mon to Thu",
        columns=[
            Column(key="ad_type", header="Ad Type", type="text", blank_empty=True),
            Column(key="name", header="Campaign Name", type="text", width=44),
            Column(key="spend", header="Spends", type=money, emphasis="bar"),
            Column(key="revenue", header="Revenue", type=money, emphasis="bar"),
            Column(key="roas", header="ROAS", type="rating"),
        ],
        rows=[
            {"ad_type": sec.label if i == 0 else None, "name": c.name, "is_total": False,
             "spend": c.weekday.spend, "revenue": c.weekday.revenue, "roas": c.weekday.roas}
            for sec in report.sections
            for i, c in enumerate(sec.campaigns)
        ],
        total_row={
            "ad_type": "Grand Total", "name": None, "is_total": True,
            "spend": report.totals.weekday.spend,
            "revenue": report.totals.weekday.revenue,
            "roas": report.totals.weekday.roas,
        },
        highlight_key="is_total",
    )

    out = [planning, weekday]
    if report.banners:
        out.append(
            Section(
                key="banner_listing_ads",
                title="Banner Listing Ads",
                description="Banner campaigns, judged on what an impression cost.",
                context=f"{report.start:%d %b} to {report.end:%d %b %Y}",
                columns=[
                    Column(key="name", header="Campaign Name", type="text", width=44),
                    Column(key="spend", header="Spends", type=money, emphasis="bar"),
                    Column(key="impressions", header="Impressions", type="count"),
                    Column(
                        key="spend_per_impression",
                        header="Spend per 1,000 Impressions",
                        type="money_fine",
                        emphasis="good_low",
                    ),
                ],
                rows=[b.model_dump() for b in report.banners],
                notes=[
                    "Banner placements carry no revenue attribution, so there is no RoAS to "
                    "report. Cost per thousand impressions is what the platform charges on.",
                ],
            )
        )
    return out


def _raw_sheet(title: str, rows: list[dict]) -> Section:
    """A raw export sheet: the platform's own columns, unaggregated.

    `dense=True` because these run to thousands of rows and per-cell banding and
    conditional formatting cost more than the data itself.
    """
    return Section(
        key=title.lower(),
        title=title,
        description="One row per date, campaign and targeting value, straight from the daily scrape.",
        context=f"{len(rows):,} rows",
        columns=[
            Column(key="date", header="Date", type="date"),
            Column(key="campaign_id", header="Campaign ID", type="id"),
            Column(key="campaign_name", header="Campaign Name", type="text", width=40),
            Column(key="targeting_type", header="Targeting Type", type="text"),
            Column(key="targeting_value", header="Targeting Value", type="text", width=28),
            Column(key="match_type", header="Match Type", type="text"),
            Column(key="most_viewed_position", header="Most Viewed Position", type="count"),
            Column(key="pacing_type", header="Pacing Type", type="text"),
            Column(key="cpm", header="CPM", type=MONEY),
            Column(key="impressions", header="Impressions", type="count"),
            Column(key="direct_atc", header="Direct ATC", type="count"),
            Column(key="indirect_atc", header="Indirect ATC", type="count"),
            Column(key="direct_quantities_sold", header="Direct Quantities Sold", type="count"),
            Column(key="indirect_quantities_sold", header="Indirect Quantities Sold", type="count"),
            Column(key="direct_sales", header="Direct Sales", type=MONEY),
            Column(key="indirect_sales", header="Indirect Sales", type=MONEY),
            Column(key="new_users_acquired", header="New Users Acquired", type="count"),
            Column(key="budget_consumed", header="Estimated Budget Consumed", type=MONEY),
            Column(key="direct_roas", header="Direct RoAS", type="rating"),
            Column(key="total_roas", header="Total RoAS", type="rating"),
        ],
        rows=rows,
        dense=True,
    )


def _marketing(report) -> Section:
    return Section(
        key="marketing",
        title="Marketing Ledger",
        description="Spend, attributed revenue and what the two imply, day by day.",
        context=f"{report.start:%d %b} to {report.end:%d %b %Y} · {len(report.rows)} days",
        columns=[
            Column(key="date", header="Date", type="date"),
            Column(key="spend", header="Ad Spend", type=MONEY, emphasis="bar"),
            Column(key="ad_revenue", header="Ad Revenue", type=MONEY, emphasis="bar"),
            Column(key="roas", header="RoAS", type="rating"),
            Column(key="organic_revenue", header="Organic Revenue", type=MONEY),
            Column(key="total_revenue", header="Total Revenue", type=MONEY),
            Column(key="roi", header="ROI", type="rating"),
            Column(key="impressions", header="Impressions", type="count"),
        ],
        rows=[r.model_dump() for r in report.rows],
        total_row={
            "date": "Total",
            "spend": report.totals.spend,
            "ad_revenue": report.totals.ad_revenue,
            "organic_revenue": report.totals.organic_revenue,
            "total_revenue": report.totals.total_revenue,
        },
        notes=[
            "Organic revenue is total seller revenue minus the revenue Blinkit attributes "
            "to ads, floored at zero.",
            "RoAS and ROI in the totals row are recomputed from the summed inputs, never "
            "averaged across days.",
        ],
    )


def _competition(report) -> Section:
    """Own products and competitors on the same search, one row each.

    `CompGroup` keeps the two apart (`own` / `competitors`); the sheet flattens
    them with an Own column, because the comparison IS the report and a reader
    should not have to hold two lists in their head to make it.
    """
    rows: list[dict] = []
    for group in report.groups:
        for label, items in (("Yes", group.own), ("", group.competitors)):
            for r in items:
                d = r.model_dump()
                pack = (
                    f"{d['pack_size']:g} {d['pack_uom']}"
                    if d.get("pack_size") and d.get("pack_uom")
                    else None
                )
                rows.append(
                    {
                        "keyword": group.keyword,
                        "marketplace": group.marketplace,
                        "own": label,
                        "name": d["name"],
                        "brand": d["brand"],
                        "pack": pack,
                        "mrp": d["mrp"],
                        "sp": d["sp"],
                        "unit_price": d["unit_price"],
                    }
                )
    return Section(
        key="competition",
        title="Price vs Competitors",
        description="Own price against competitors on the same search, normalised per unit.",
        context=f"{report.start:%d %b} to {report.end:%d %b %Y} · {report.kind} SKUs",
        columns=[
            Column(key="keyword", header="Keyword", type="text"),
            Column(key="marketplace", header="Marketplace", type="text"),
            Column(key="own", header="Ours", type="text"),
            Column(key="name", header="Product", type="text", width=44),
            Column(key="brand", header="Brand", type="text"),
            Column(key="pack", header="Pack", type="text"),
            Column(key="mrp", header="MRP", type=MONEY),
            Column(key="sp", header="Selling Price", type=MONEY),
            Column(key="unit_price", header="Per Unit", type="money_fine", emphasis="good_low"),
        ],
        rows=rows,
        highlight_key="own",
        notes=[
            "Per unit is price divided by pack size (₹ per 100 ml, 100 g or piece), so packs "
            "of different sizes compare fairly.",
        ],
    )


async def build_file(
    session: AsyncSession,
    *,
    which: str,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    marketplaces: list[str] | None = None,
    metric: str = "value",
    view: str = "daily",
    kind: str = "main",
    client_name: str | None = None,
) -> tuple[str, str]:
    """Render the SELECTED report to an .xlsx. Returns (path, filename)."""
    sections: list[Section] = []
    section: Section | None = None

    if which == "sales":
        pivot = await reports_service.get_sales_pivot(
            session, tenant_id=tenant_id, start=start, end=end,
            marketplaces=marketplaces, metric=metric,
        )
        if not pivot.platforms:
            raise ValueError("No sales in that window.")
        if view == "weekly" and not pivot.weeks:
            raise ValueError(
                "That window holds no complete Monday to Sunday week, so the weekly view "
                "has nothing to export."
            )
        section = _sales_weekly(pivot) if view == "weekly" else _sales_daily(pivot)
    elif which == "weekend":
        rep = await reports_service.get_weekend_planning(
            session, tenant_id=tenant_id, start=start, end=end, marketplaces=marketplaces
        )
        if not rep.sections:
            raise ValueError("No campaign activity in that window.")
        sections = _weekend(rep)
        for ctype, title in (
            ("PRODUCT_LISTING", "PRODUCT_LISTING"),
            ("PRODUCT_RECOMMENDATION", "PRODUCT_RECOMMENDATION"),
        ):
            raw = await reports_service.get_raw_ad_rows(
                session, tenant_id=tenant_id, start=start, end=end, campaign_type=ctype
            )
            if raw:
                sections.append(_raw_sheet(title, raw))
        # BANNER_LISTING raw is deliberately absent: Reach, CTR and Unique Clicks
        # are not collected, and a sheet with three empty columns is worse than a
        # sheet that is honestly not there.
        section = None
    elif which == "marketing":
        rep = await reports_service.get_marketing_report(
            session, tenant_id=tenant_id, start=start, end=end, marketplaces=marketplaces
        )
        if not rep.rows:
            raise ValueError("No marketing data in that window.")
        section = _marketing(rep)
    elif which == "competition":
        rep = await reports_service.get_competition_report(
            session, tenant_id=tenant_id, start=start, end=end,
            marketplaces=marketplaces, kind=kind,
        )
        if not rep.groups:
            raise ValueError("No competition data in that window.")
        section = _competition(rep)
    else:
        raise ValueError(f"Unknown report '{which}'.")

    if section is not None:
        sections = [section]

    report = Report(
        title=sections[0].title,
        subtitle=f"{client_name or ''} · {start:%d %b %Y} to {end:%d %b %Y}".strip(" ·"),
        sections=sections,
        filename_stem=sections[0].key,
    )
    name = f"{sections[0].title.replace(' ', '_')}_{start:%Y-%m-%d}_to_{end:%Y-%m-%d}.xlsx"
    path = f"{mkdtemp(prefix='report-')}/{name}"
    write_workbook(report, path)
    return path, name
