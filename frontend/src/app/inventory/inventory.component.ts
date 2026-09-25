import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ApiService } from '../api.service';
import { Sample } from '../models';

@Component({
  selector: 'app-inventory',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="panel">
      <h2>样本清单与来源关系</h2>
      <div class="actions">
        <button (click)="reset()">载入演示数据（16 个样本）</button>
        <span class="muted" *ngIf="loading">加载中…</span>
      </div>
    </div>

    <div class="panel">
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>样本编号</th><th>类型</th><th>类别</th><th>采集时间</th>
              <th>登记主体</th><th>来源样本</th><th>说明</th>
            </tr>
          </thead>
          <tbody>
            <tr *ngFor="let s of samples">
              <td>{{ s.sample_code }}</td>
              <td>{{ kindText(s.kind) }}</td>
              <td>{{ s.label }}</td>
              <td>{{ s.collected_at.replace('T', ' ').slice(0, 16) }}</td>
              <td>{{ s.subject_key || '—' }}</td>
              <td>
                {{ s.source_sample_code || '—' }}
                <span class="chip bad" *ngIf="isDangling(s.sample_code)">来源不存在</span>
              </td>
              <td>{{ describe(s) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="muted" style="margin-top:10px">
        演示包含：跨 5 月/7 月的主体、罕见类别 rare-anomaly、正常裁切继承、来源缺失样本、来源成环、无主体原始样本。
      </p>
    </div>
  `,
})
export class InventoryComponent implements OnInit {
  private api = inject(ApiService);
  samples: Sample[] = [];
  loading = false;

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.loading = true;
    this.api.listSamples().subscribe((data) => {
      this.samples = data;
      this.loading = false;
    });
  }

  reset(): void {
    this.api.resetDemo().subscribe(() => this.load());
  }

  kindText(kind: string): string {
    const map: Record<string, string> = { original: '原始', crop: '裁切', augment: '增强' };
    return map[kind] || kind;
  }

  private get validCodes(): Set<string> {
    return new Set(this.samples.map((s) => s.sample_code));
  }

  isDangling(code: string): boolean {
    const s = this.samples.find((x) => x.sample_code === code);
    return !!s?.source_sample_code && !this.validCodes.has(s.source_sample_code);
  }

  describe(s: Sample): string {
    if (s.kind !== 'original' && !s.source_sample_code) return '派生样本但无来源登记';
    if (s.kind === 'original' && !s.subject_key) return '原始样本缺少主体';
    if (this.isDangling(s.sample_code)) return '派生样本无法追溯到原始来源';
    return '';
  }
}
