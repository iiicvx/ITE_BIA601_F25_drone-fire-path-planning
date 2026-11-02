"""اختبارات simulation/experiments.py والتجارب النهائية المحفوظة.

* قوائم المهام تتشارك المدن وميزانيات البحث العشوائي، مع تشغيل حتمي واحد لـ DP في كل مدينة
* تحتفظ التشغيلات بالزمن والذاكرة وحكم المدقق، وتُتجاوز المهام المحفوظة المطابقة عند الاستئناف
* يُفحص اكتمال الدراسة المحفوظة واتساقها عند وجود الأرشيف
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from simulation import experiments as R
from simulation.experiments import run_job
from simulation.stats import build_all

CFG = R.load_config()
SAVED = R.ROOT / "results/experiments/runs.csv"


# قوائم المهام
def test_job_counts_follow_the_proposal():
    main, rnd, dps = (R.make_jobs(p, CFG) for p in ("main", "random", "dp_sensitivity"))
    assert len(main) == 3 * (3 * 20 + 1)                      # GA وPSO وACO × 20 بذرة + DP مرة واحدة، 3 مدن
    assert len(rnd) == 3 * 10 * 4                             # 10 مدن عشوائية لكل حجم، البذرة 0
    assert len(dps) == 2 * 3 * 2
    names = [R.job_name(j) for j in main + rnd + dps]
    assert len(set(names)) == len(names)                      # لكل تشغيل ملفه الخاص


def test_every_algorithm_gets_the_same_conditions():
    for part in ("main", "random"):
        jobs = pd.DataFrame(R.make_jobs(part, CFG))
        assert jobs["budget"].isna().all()                    # ميزانية المدينة نفسها (10k / 24k / 40k) للجميع
        assert (jobs["params"].map(len) == 0).all()           # الإعدادات المجمدة في algorithms.yaml للجميع
        for city, g in jobs.groupby("city"):
            seeds = {a: set(gg["seed"]) for a, gg in g.groupby("alg")}
            assert seeds["ga"] == seeds["pso"] == seeds["aco"]
            assert seeds["dp"] == {0}
    main = pd.DataFrame(R.make_jobs("main", CFG))
    assert set(main[main["alg"] == "ga"]["seed"]) == set(range(20))


def test_longest_runs_start_first():
    jobs = sorted(R.make_jobs("main", CFG), key=lambda j: -R.expected_seconds(j))
    assert jobs[0]["alg"] == "aco" and jobs[0]["city"] == "large"
    assert jobs[-1]["alg"] == "dp" and jobs[-1]["city"] == "small"


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="peak memory is read from /proc on Linux")
def test_peak_memory_measurement():
    base, method = R.memory_start()
    block = np.ones(8_000_000)                                 # 64 MB ثم تُحرَّر
    del block
    assert method == "linux_peak_rss" and R.memory_peak(method) - base > 55


# التشغيل والاستئناف
def tiny_config():
    cfg = json.loads(json.dumps(CFG))
    cfg["algorithms"] = ["ga", "dp"]
    cfg["main"] = {"cities": ["small"], "seeds": 2}
    return cfg


def test_runs_are_saved_measured_checked_and_not_repeated(tmp_path, capsys):
    cfg = tiny_config()
    R.run_part("main", cfg, tmp_path, jobs_n=2, trial=True)            # ميزانية قصيرة من 300 تقييم
    files = sorted((tmp_path / "runs" / "main").glob("*.json"))
    assert [f.stem for f in files] == ["dp_small_s0", "ga_small_s0", "ga_small_s1"]
    r = json.loads(files[1].read_text())
    assert r["job"] == {"alg": "ga", "city": "small", "seed": 0, "params": {}, "budget": 300}
    assert r["fe_used"] == 300 and r["cpu_s"] > 0 and r["time_s"] > 0
    assert r["validator"]["agrees_with_fitness"] and r["validator"]["valid"] == r["feasible"]
    if sys.platform.startswith("linux"):
        assert r["memory_method"] == "linux_peak_rss" and r["memory_mb"] >= 0
    assert run_job(r["job"])["best_f"] == r["best_f"]                  # التشغيل المحفوظ قابل للإعادة
    capsys.readouterr()
    R.run_part("main", cfg, tmp_path, jobs_n=2, trial=True)
    assert "3 already saved, 0 to do" in capsys.readouterr().out       # التشغيل المتوقف يُستأنف
    cfg["main"]["seeds"] = 3
    R.run_part("main", cfg, tmp_path, jobs_n=2, trial=True)
    assert "3 already saved, 1 to do" in capsys.readouterr().out
    res = build_all(tmp_path, cfg, figures=tmp_path / "fig")
    assert res["checks"]["validator_disagrees_with_F"] == 0
    assert (tmp_path / "tables.md").exists() and (tmp_path / "main_summary.csv").exists()
    assert {p.name for p in (tmp_path / "fig").glob("*.png")} >= {"convergence.png", "distribution.png", "cost.png"}


def test_a_changed_setting_is_run_again(tmp_path):
    job = {"alg": "dp", "city": "small", "seed": 0, "params": {}, "budget": None}
    path = tmp_path / "dp_small_s0.json"
    path.write_text(json.dumps({"job": {**job, "budget": 5}}))
    assert R.saved_job(path) != job
    path.write_text("not json")
    assert R.saved_job(path) is None


# التجارب النهائية المحفوظة
@pytest.fixture(scope="module")
def runs():
    if not SAVED.exists():
        pytest.skip("run python -m simulation.experiments first")
    return pd.read_csv(SAVED)


def test_saved_main_experiment_is_complete_and_fair(runs):
    main = runs[runs["part"] == "main"]
    for city in ("small", "medium", "large"):
        m = main[main["city"] == city]
        for alg in ("GA", "PSO", "ACO"):
            assert sorted(m[m["algorithm"] == alg]["seed"]) == list(range(20)), (city, alg)
        assert list(m[m["algorithm"] == "DP"]["seed"]) == [0]
        assert m["budget"].nunique() == 1                                # ميزانية واحدة لكل خوارزمية
        assert (m["fe_used"] <= m["budget"]).all()


def test_saved_random_experiment_is_complete(runs):
    rnd = runs[runs["part"] == "random"]
    assert len(rnd) == 120
    assert (rnd.groupby("city")["algorithm"].nunique() == 4).all()


def test_every_saved_run_was_checked_and_agrees(runs):
    assert runs["agree"].all()                                           # F والمدقق: الحكم نفسه
    assert runs["memory_mb"].notna().all() and (runs["cpu_s"] > 0).all()
