import { app } from "../../scripts/app.js";

// 旧工作流迁移（载入时自动纠正非法控件值，否则后端校验会直接拒绝排队）
//
// 1) 「单次缓存清理 / 双次缓存清理」已删除，只剩 不做任何清理 / 卸载显存模型 / 卸载全量模型
// 2) 三个（旧）VAE 解码节点已并入新节点：旧参数里 0 表示「用默认值」（运行时映射为 512/64/8），
//    但新节点直接用官方参数且有 min 约束，0 属于非法值，这里夹回默认值
const LEGACY_CLEANUP_VALUES = new Set(["单次缓存清理", "双次缓存清理"]);
const CLEANUP_FALLBACK = "不做任何清理";

// 旧节点直接改写为新节点类型（载入时完成，重新保存即永久生效）。
// slots：对应旧控件数组的每一格，zero = 旧值 0 的等价默认值，min/max = 新控件约束（不需要改值的节点可省略）
// renames：旧参数名 → 新参数名（子图里"提升"出来的控件靠名字对齐，改名必须同步）
const LEGACY_CONVERT = {
	XB_ROCmVAEDecode: {
		type: "XB_VAEDecodeTiledImage",
		slots: [{ zero: 512, min: 256, max: 4096 }, { min: 0, max: 256 }, null],
	},
	XB_ROCmVAEDecodeTemporal: {
		type: "XB_VAEDecodeTiled",
		slots: [
			{ zero: 512, min: 64, max: 4096 },
			{ min: 0, max: 4096 },
			{ zero: 64, min: 8, max: 4096 },
			{ zero: 8, min: 4, max: 4096 },
			null,
		],
	},
	XB_ROCmKSampler: {
		type: "XB_KSampler",
		renames: { latent: "latent_image", sampler: "sampler_name" },
	},
	XB_ROCmKSamplerAdvanced: {
		type: "XB_KSamplerAdvanced",
		renames: { latent: "latent_image", sampler: "sampler_name" },
	},
	XB_ROCmSamplerCustom: { type: "XB_SamplerCustom" },
	XB_ROCmSamplerCustomAdvanced: { type: "XB_SamplerCustomAdvanced" },
};
LEGACY_CONVERT.XB_ROCmLTXVAEDecode = LEGACY_CONVERT.XB_ROCmVAEDecodeTemporal;

// 子图里被"提升"到外面的控件靠名字对齐，改名时必须同步输入项，否则连线/取值会错位
const LEGACY_WIDGET_RENAMES = { tile: "tile_size", t_tile: "temporal_size", t_overlap: "temporal_overlap" };

function renamePromotedWidgets(node, extraRenames) {
	const renames = { ...LEGACY_WIDGET_RENAMES, ...(extraRenames || {}) };
	for (const input of node.inputs || []) {
		const current = input?.widget?.name ?? input?.name;
		const renamed = renames[current];
		if (!renamed) continue;
		if (input.widget) input.widget.name = renamed;
		if (input.name === current) input.name = renamed;
	}
}

function convertLegacyNode(node) {
	const spec = LEGACY_CONVERT[node?.type];
	if (!spec) return false;
	const values = Array.isArray(node.widgets_values) ? node.widgets_values.slice() : null;
	if (values) {
		(spec.slots || []).forEach((slot, i) => {
			if (!slot || typeof values[i] !== "number") return;
			let v = values[i];
			if (slot.zero !== undefined && !(v > 0)) v = slot.zero;
			values[i] = Math.min(slot.max, Math.max(slot.min, v));
		});
		for (let i = 0; i < values.length; i++) {
			if (typeof values[i] === "string" && LEGACY_CLEANUP_VALUES.has(values[i])) values[i] = CLEANUP_FALLBACK;
		}
	}
	node.type = spec.type;
	if (values) node.widgets_values = values;
	renamePromotedWidgets(node, spec.renames);
	if (typeof node.properties === "object" && node.properties) {
		if (node.properties["Node name for S&R"] in LEGACY_CONVERT) node.properties["Node name for S&R"] = spec.type;
	}
	return true;
}

function convertGraphData(graphData) {
	let count = 0;
	const walkNodes = (nodes) => {
		for (const node of nodes || []) if (convertLegacyNode(node)) count++;
	};
	const walkDefinitions = (defs) => {
		for (const subgraph of defs?.subgraphs || []) {
			walkNodes(subgraph.nodes);
			walkDefinitions(subgraph.definitions);
		}
	};
	walkNodes(graphData?.nodes);
	walkDefinitions(graphData?.definitions);
	return count;
}

function sanitizeWidgets(node, defaults) {
	for (const w of node.widgets || []) {
		const opts = w?.options || {};
		if (typeof w.value === "string" && LEGACY_CLEANUP_VALUES.has(w.value)) {
			const values = opts.values;
			w.value =
				Array.isArray(values) && values.includes(CLEANUP_FALLBACK) ? CLEANUP_FALLBACK : (values?.[0] ?? w.value);
			continue;
		}
		if (typeof w.value === "number" && typeof opts.min === "number" && w.value < opts.min) {
			const fallback = defaults?.[w.name];
			w.value = typeof fallback === "number" ? fallback : opts.min;
		}
	}
}

app.registerExtension({
	name: "XB_ToolBox.LegacyNodeMigrate",
	async beforeConfigureGraph(graphData) {
		try {
			convertGraphData(graphData);
		} catch (e) {
			console.warn("[XB_ToolBox] 旧节点升级失败", e);
		}
	},
	async beforeRegisterNodeDef(nodeType, nodeData) {
		const cleanupOptions = nodeData?.input?.required?.cleanup?.[0];
		if (!Array.isArray(cleanupOptions) || !cleanupOptions.includes("卸载全量模型")) return;

		// 控件 options 里不带 default（前端只保留 min/max/step），默认值只能从节点定义里取
		const defaults = {};
		for (const [name, spec] of Object.entries(nodeData?.input?.required || {})) {
			const defaultValue = spec?.[1]?.default;
			if (typeof defaultValue === "number") defaults[name] = defaultValue;
		}

		const proto = nodeType.prototype;
		const origOnConfigure = proto.onConfigure;
		proto.onConfigure = function () {
			const result = origOnConfigure?.apply(this, arguments);
			try {
				sanitizeWidgets(this, defaults);
			} catch (e) {
				/* 迁移失败不影响节点载入，用户手动改一下即可 */
			}
			return result;
		};
	},
});
