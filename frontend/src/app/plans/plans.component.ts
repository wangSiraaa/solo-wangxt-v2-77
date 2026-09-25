import { Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ApiService } from '../api.service';
import { Assignment, PlanSummary, REASON_TEXT } from '../models';

@Component({
  selector: 'app-plans',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="panel">
      <h2>已保存的拆分方案</h2>
      <div class="actions" style="margin-top:0">
        <button class="ghost" (click)="load()">刷新</button>
      </div>
      <table style="margin-top:10px">
        <thead>
          <tr>
            <th>方案</th><th>状态</th><th>时间分界</th><th>策略</th>
            <th>种子</th><th>目标/实际评测比例</th><th>隔离样本</th><th></th>
          </tr>
        </thead>
        <tbody>
          <tr *ngFor="let p of plans()">
            <td>{{ p.name }}<br><span class="muted">{{ fmt(p.created_at) }}</span></td>
            <td><span class="badge" [class]="p.status">{{ p.status === 'confirmed' ? '已确认' : '预览' }}</span></td>
            <td>{{ p.cutoff_date }}</td>
            <td>{{ policyText(p.cutoff_policy) }}</td>
            <td>{{ p.seed }}</td>
            <td>
              {{ (p.stats.target_eval_ratio * 100).toFixed(0) }}% /
              {{ (p.stats.actual_eval_ratio * 100).toFixed(1) }}%
            </td>
            <td>{{ p.stats.excluded_samples }}</td>
            <td><button class="ghost" (click)="open(p.id)">查看每个样本</button></td>
          </tr>
          <tr *ngIf="plans().length === 0"><td colspan="8" class="muted">暂无方案，请先在“拆分核查”页生成并确认。</td></tr>
        </tbody>
      </table>
    </div>

    <div class="panel" *ngIf="detailAssignments() as rows">
      <h2>方案明细：{{ detailId()?.slice(0, 8) }}（{{ rows.length }} 个样本）</h2>
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>样本</th><th>归属</th><th>有效主体</th><th>类别</th><th>原因</th></tr>
          </thead>
          <tbody>
            <tr *ngFor="let a of rows">
              <td>{{ a.sample_code }}<span class="chip" *ngIf="a.inherited">继承</span></td>
              <td><span class="badge" [class]="a.assignment">{{
                a.assignment === 'train' ? '训练' : a.assignment === 'eval' ? '评测' : '隔离'
              }}</span></td>
              <td>{{ a.effective_subject_key ?? '— 未知 —' }}</td>
              <td>{{ a.label }}</td>
              <td>
                <span *ngFor="let reason of a.reasons" class="chip"
                  [class.bad]="['missing_source_ref','source_cycle','train_after_cutoff_violation'].includes(reason)"
                  [class.warn]="['cutoff_crossing','missing_subject'].includes(reason)"
                  [class.ok]="!['missing_source_ref','source_cycle','train_after_cutoff_violation','cutoff_crossing','missing_subject'].includes(reason)">
                  {{ reasonText[reason] || reason }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  `,
})
export class PlansComponent implements OnInit {
  private api = inject(ApiService);
  plans = signal<PlanSummary[]>([]);
  detailAssignments = signal<Assignment[] | null>(null);
  detailId = signal<string | null>(null);
  reasonText = REASON_TEXT;

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.api.listPlans().subscribe((data) => this.plans.set(data));
  }

  open(id: string): void {
    this.api.planDetail(id).subscribe((d) => {
      this.detailId.set(id);
      this.detailAssignments.set(d.assignments);
    });
  }

  policyText(p: string): string {
    return { exclude: '隔离剔除', eval: '强制评测', train: '强制训练' }[p] || p;
  }

  fmt(v: string | null): string {
    return v ? v.replace('T', ' ').slice(0, 16) : '';
  }
}
