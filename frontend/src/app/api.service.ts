import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

export interface Sample {
  id: string;
  label: string;
  captured_at: string;
  subject_id: string | null;
  parent_id: string | null;
  kind: 'original' | 'crop' | 'augment';
}

export interface SplitRequest {
  cutoff: string;
  subject_field: string;
  target_eval_ratio: Record<string, number>;
  seed: number | null;
  time_mode: 'hard' | 'grouped_stratify';
  straddle_policy: 'train_lock' | 'eval_lock';
}

export interface RatioStat {
  target: number | null;
  actual: number | null; // null = 该类别没有任何可拆分样本
  diff: number | null;
  train: number;
  eval: number;
  excluded?: number;
  unresolved?: number;
}

export interface Assignment {
  sample_id: string;
  bucket: string;
  root_subject: string | null;
  reason: string | null;
}

export interface Conflict {
  subject: string | null;
  conflict_type: string;
  severity: string;
  detail: string;
  sample_ids: string[];
}

export interface SplitResult {
  run_id: number;
  status: string;
  cutoff: string;
  seed: number;
  time_mode: string;
  straddle_policy: string;
  subject_field: string;
  target_ratios: Record<string, number>;
  buckets: Record<string, number>;
  ratios: Record<string, RatioStat>;
  warnings: string[];
  leakage_statement: string;
  assignments: Assignment[];
  conflicts: Conflict[];
}

@Injectable({ providedIn: 'root' })
export class ApiService {
  constructor(private http: HttpClient) {}

  private base = '/api';

  listSamples(): Observable<Sample[]> {
    return this.http.get<Sample[]>(`${this.base}/samples`);
  }

  bulkSamples(samples: Sample[]): Observable<{ created: number }> {
    return this.http.post<{ created: number }>(`${this.base}/samples/bulk`, samples);
  }

  previewSplit(req: SplitRequest): Observable<SplitResult> {
    return this.http.post<SplitResult>(`${this.base}/splits/preview`, req);
  }

  confirmRun(runId: number): Observable<SplitResult> {
    return this.http.post<SplitResult>(`${this.base}/splits/${runId}/confirm`, {});
  }

  getRun(runId: number): Observable<SplitResult> {
    return this.http.get<SplitResult>(`${this.base}/splits/${runId}`);
  }

  listRuns(): Observable<SplitResult[]> {
    return this.http.get<SplitResult[]>(`${this.base}/splits`);
  }
}
