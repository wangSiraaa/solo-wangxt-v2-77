import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { InventoryComponent } from './inventory/inventory.component';
import { SplitComponent } from './split/split.component';
import { PlansComponent } from './plans/plans.component';

type Tab = 'inventory' | 'split' | 'plans';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule, InventoryComponent, SplitComponent, PlansComponent],
  template: `
    <div class="container">
      <h1>LeakGuard · 训练集 / 评测集来源泄漏核查</h1>
      <p class="subtitle">
        主体级隔离 · 时间分界 · pandas + scikit-learn 分层拆分 · PostgreSQL 持久化随机种子。
        不训练真实模型；未知来源关系只隔离、不背书。
      </p>

      <div class="actions" style="margin-bottom:16px">
        <button class="ghost" (click)="tab = 'inventory'">① 样本清单</button>
        <button class="ghost" (click)="tab = 'split'">② 拆分核查</button>
        <button class="ghost" (click)="tab = 'plans'">③ 已保存方案</button>
      </div>

      <app-inventory *ngIf="tab === 'inventory'" />
      <app-split *ngIf="tab === 'split'" />
      <app-plans *ngIf="tab === 'plans'" />
    </div>
  `,
})
export class AppComponent {
  tab: Tab = 'inventory';
}
