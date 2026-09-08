// 融资动态表格专属维度定义（与 taxonomy.json → funding.*_dim 对齐）
// 仅用于融资动态表格模式（FundingTableView）的 TagFilterBar 注入

export const FUNDING_DIMENSIONS: Record<string, { label: string; values: string[] }> = {
  industry: { label: "所属行业", values: ["AI游戏", "AI社交/陪伴", "AI互动内容/娱乐", "AI创作工具/生产力", "AI模型/基础设施", "具身智能/机器人", "其他"] },
  company_type: { label: "公司类型", values: ["初创公司", "大厂/已上市", "其他"] },
  region: { label: "国家/地区", values: ["中国", "美国", "欧洲", "东南亚", "日韩", "其他"] },
};


export const FUNDING_DIM_IDS = ["industry", "company_type", "region"] as const;
