import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { PlanSummary, PreviewResponse, Sample } from './models';

export interface SplitForm {
  name: string;
  cutoff_date: string;
  target_eval_ratio: number;
  seed: number;
  cutoff_policy: 'exclude' | 'eval' | 'train';
  target_label_ratios: Record<string, number>;
}

@Injectable({ providedIn: 'root' })
export class ApiService {
  private http = inject(HttpClient);
  private base = '/api';

  listSamples(): Observable<Sample[]> {
    return this.http.get<Sample[]>(`${this.base}/samples`);
  }

  resetDemo(): Observable<{ loaded_samples: number; subjects: number }> {
    return this.http.post<{ loaded_samples: number; subjects: number }>(
      `${this.base}/demo/reset`,
      {}
    );
  }

  preview(form: SplitForm): Observable<PreviewResponse> {
    return this.http.post<PreviewResponse>(`${this.base}/splits/preview`, {
      ...form,
      subject_field: 'subject_id',
    });
  }

  confirm(planId: string): Observable<unknown> {
    return this.http.post(`${this.base}/splits/confirm`, { plan_id: planId });
  }

  listPlans(): Observable<PlanSummary[]> {
    return this.http.get<PlanSummary[]>(`${this.base}/splits`);
  }

  planDetail(planId: string): Observable<{ plan: PlanSummary; assignments: import('./models').Assignment[] }> {
    return this.http.get<{ plan: PlanSummary; assignments: import('./models').Assignment[] }>(
      `${this.base}/splits/${planId}`
    );
  }
}
