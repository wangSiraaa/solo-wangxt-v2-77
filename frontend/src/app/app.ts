import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import {
  ApiService,
  Assignment,
  Conflict,
  Sample,
  SplitRequest,
  SplitResult,
} from './api.service';

interface SubjectGroup {
  subject: string;
  assignments: Assignment[];
  buckets: Set<string>;
  hasLeak: boolean;
  hasStraddle: boolean;
}

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './app.html',
  styleUrl: './app.css',
})
export class App implements OnInit {
  samples: Sample[] = [];
  result: SplitResult | null = null;
  loading = false;
  error = '';
  confirmed = false;

  // Form
  cutoff = '2026-08-01';
  subjectField = 'subject_id';
  timeMode: 'hard' | 'grouped_stratify' = 'hard';
  straddlePolicy: 'train_lock' | 'eval_lock' = 'train_lock';
  defaultRatio = 0.2;
  rareRatio = 0.5;
  rareClass = 'rare_anomaly';
  seed: number | null = 42;

  filterBucket = '';

  constructor(private api: ApiService) {}

  ngOnInit(): void {
    this.refresh();
  }

  refresh(): void {
    this.loading = true;
    this.api.listSamples().subscribe({
      next: (rows) => {
        this.samples = rows;
        this.loading = false;
      },
      error: (e) => {
        this.error = `无法连接后端 API：${e.message}`;
        this.loading = false;
      },
    });
  }

  buildRequest(): SplitRequest {
    return {
      cutoff: this.cutoff,
      subject_field: this.subjectField,
      target_eval_ratio: {
        __default__: this.defaultRatio,
        [this.rareClass]: this.rareRatio,
      },
      seed: this.seed,
      time_mode: this.timeMode,
      straddle_policy: this.straddlePolicy,
    };
  }

  preview(): void {
    this.loading = true;
    this.error = '';
    this.confirmed = false;
    this.api.previewSplit(this.buildRequest()).subscribe({
      next: (r) => {
        this.result = r;
        this.confirmed = r.status === 'confirmed';
        this.loading = false;
      },
      error: (e) => {
        this.error = e?.error?.detail ?? e.message;
        this.loading = false;
      },
    });
  }

  confirm(): void {
    if (!this.result) return;
    this.loading = true;
    this.api.confirmRun(this.result.run_id).subscribe({
      next: (r) => {
        this.result = r;
        this.confirmed = true;
        this.loading = false;
      },
      error: (e) => {
        this.error = e?.error?.detail ?? e.message;
        this.loading = false;
      },
    });
  }

  ratioEntries() {
    if (!this.result) return [];
    return Object.entries(this.result.ratios)
      .filter(([label]) => label !== '__default__')
      .map(([label, stat]) => ({ label, stat }));
  }

  get bucketCounts() {
    return this.result?.buckets ?? {};
  }

  /** Group assignments by resolved ORIGIN subject for the leakage view. */
  get subjectGroups(): SubjectGroup[] {
    if (!this.result) return [];
    const map = new Map<string, Assignment[]>();
    for (const a of this.result.assignments) {
      const key = a.root_subject ?? '（无主体 / 来源未确认）';
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(a);
    }
    const groups: SubjectGroup[] = [];
    for (const [subject, assignments] of map) {
      const buckets = new Set(assignments.map((a) => a.bucket));
      const hasLeak = buckets.has('train') && buckets.has('eval');
      const hasStraddle = assignments.some((a) => a.reason?.includes('时间分界'));
      groups.push({ subject, assignments, buckets, hasLeak, hasStraddle });
    }
    return groups.sort((a, b) => (a.subject < b.subject ? -1 : 1));
  }

  get filteredAssignments(): Assignment[] {
    if (!this.result) return [];
    if (!this.filterBucket) return this.result.assignments;
    return this.result.assignments.filter((a) => a.bucket === this.filterBucket);
  }

  sampleOf(id: string): Sample | undefined {
    return this.samples.find((s) => s.id === id);
  }

  bucketLabel(b: string): string {
    return {
      train: '训练 train',
      eval: '评测 eval',
      excluded: '剔除 excluded',
      unresolved: '未决 unresolved',
    }[b] ?? b;
  }

  bucketList(g: SubjectGroup): string {
    return Array.from(g.buckets).join(', ');
  }

  protected readonly Math = Math;

  conflictIcon(c: Conflict): string {
    return c.severity === 'error' ? '⛔' : c.severity === 'warning' ? '⚠️' : 'ℹ️';
  }
}
