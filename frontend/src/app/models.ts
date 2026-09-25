export interface Sample {
  sample_code: string;
  kind: string;
  label: string;
  collected_at: string;
  subject_key: string | null;
  source_sample_code: string | null;
}

export interface Assignment {
  sample_code: string;
  effective_subject_key: string | null;
  assignment: 'train' | 'eval' | 'excluded';
  reasons: string[];
  inherited: boolean;
  label: string;
  collected_at: string;
  kind: string;
}

export interface PerLabel {
  total: number;
  eval: number;
  train: number;
  actual_eval_ratio: number;
  target_eval_ratio: number;
  diff: number;
}

export interface Stats {
  total_samples: number;
  used_samples: number;
  excluded_samples: number;
  train_samples: number;
  eval_samples: number;
  total_subjects: number;
  cutoff_crossing_subjects: number;
  target_eval_ratio: number;
  actual_eval_ratio: number;
  ratio_diff: number;
  per_label: Record<string, PerLabel>;
  conflict_counts: Record<string, number>;
  notes: string[];
  assertions: Record<string, boolean>;
  time_condition: Record<string, number>;
  unresolved_relationships: number;
  seed: number;
  cutoff_policy: string;
}

export interface PreviewResponse {
  plan_id: string;
  params: Record<string, unknown>;
  stats: Stats;
  assignments: Assignment[];
}

export interface PlanSummary {
  id: string;
  name: string;
  status: 'preview' | 'confirmed';
  cutoff_date: string;
  seed: number;
  target_eval_ratio: number;
  cutoff_policy: string;
  stats: Stats;
  created_at: string;
  confirmed_at: string | null;
}

export interface PlanDetail extends PlanSummary {
  assignments: Assignment[];
}

export const REASON_TEXT: Record<string, string> = {
  cutoff_crossing: '跨时间分界：主体在分界两侧均有样本',
  missing_source_ref: '来源缺失：引用了不存在/已删除的原始样本',
  source_cycle: '来源成环：无法追溯到原始样本',
  missing_subject: '缺少主体身份',
  inherited_identity: '派生样本，继承原始来源身份',
  pre_cutoff_group: '主体样本均在分界前',
  post_cutoff_group: '主体样本均在分界后，按时间条件归入评测',
  forced_eval_by_policy: '按策略强制归入评测',
  forced_train_by_policy: '按策略强制归入训练',
  train_after_cutoff_violation: '违规：训练集出现分界后样本',
  eval_contains_pre_cutoff: '评测集包含该主体分界前的样本',
};
