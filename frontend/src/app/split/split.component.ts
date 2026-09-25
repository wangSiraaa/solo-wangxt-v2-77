import { Component, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../api.service';
import { Assignment, PreviewResponse, REASON_TEXT } from '../models';

@Component({
  selector: 'app-split',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './split.component.html',
})
export class SplitComponent {
  private api = inject(ApiService);

  cutoffDate = '2024-06-01';
  subjectField = 'subject_id';
  targetRatio = 0.3;
  seed = 42;
  policy: 'exclude' | 'eval' | 'train' = 'exclude';

  result = signal<PreviewResponse | null>(null);
  confirmed = signal(false);
  error = signal('');
  filter = signal<'all' | 'train' | 'eval' | 'excluded'>('all');

  reasonText = REASON_TEXT;

  run(): void {
    this.confirmed.set(false);
    this.error.set('');
    this.api
      .preview({
        name: `plan-${this.cutoffDate}`,
        cutoff_date: this.cutoffDate,
        target_eval_ratio: Number(this.targetRatio),
        seed: Number(this.seed),
        cutoff_policy: this.policy,
        target_label_ratios: {},
      })
      .subscribe({
        next: (res) => {
          this.result.set(res);
        },
        error: (err) =>
          this.error.set(err?.error?.detail ?? '生成拆分失败，请检查参数'),
      });
  }

  confirm(): void {
    const res = this.result();
    if (!res) return;
    this.api.confirm(res.plan_id).subscribe({
      next: () => this.confirmed.set(true),
      error: (err) => this.error.set(err?.error?.detail ?? '确认失败'),
    });
  }

  pct(v: number): string {
    return (v * 100).toFixed(1) + '%';
  }

  diffClass(diff: number): string {
    return diff === 0 ? 'diff-zero' : diff > 0 ? 'diff-pos' : 'diff-neg';
  }

  reasonClass(reason: string): string {
    if (['missing_source_ref', 'source_cycle', 'train_after_cutoff_violation'].includes(reason))
      return 'chip bad';
    if (['cutoff_crossing', 'missing_subject', 'eval_contains_pre_cutoff'].includes(reason))
      return 'chip warn';
    return 'chip ok';
  }

  filteredAssignments(): Assignment[] {
    const res = this.result();
    if (!res) return [];
    const f = this.filter();
    return f === 'all'
      ? res.assignments
      : res.assignments.filter((a) => a.assignment === f);
  }

  labelEntries(): { label: string; p: any }[] {
    return Object.entries(this.result()?.stats.per_label ?? {}).map(([label, p]) => ({
      label,
      p,
    }));
  }

  reasonOf(reason: string): string {
    return this.reasonText[reason] ?? reason;
  }
}
