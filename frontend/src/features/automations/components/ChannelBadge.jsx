/**
 * Small platform monogram — Dcluttr uses real marketplace logos; we don't
 * ship those assets, so a colour-coded initial stands in. Blinkit is this
 * project's only live public/private platform today; Zepto appears once
 * `campaign_manager` data exists for it (see docs/zepto.md).
 */
const STYLE = {
	blinkit: { bg: "bg-[#f8cb46]", fg: "text-[#5a4a00]", label: "Blinkit" },
	zepto: { bg: "bg-[#8b2fc9]/15", fg: "text-[#8b2fc9]", label: "Zepto" },
};

export const ChannelBadge = ({ platform, showLabel = true }) => {
	const s = STYLE[platform] ?? {
		bg: "bg-muted",
		fg: "text-content-subtle",
		label: platform ?? "—",
	};
	return (
		<span className="inline-flex items-center gap-1.5">
			<span
				className={`flex h-4 w-4 items-center justify-center rounded text-[9px] font-bold ${s.bg} ${s.fg}`}
			>
				{s.label[0]}
			</span>
			{showLabel && <span className="text-content">{s.label}</span>}
		</span>
	);
};
