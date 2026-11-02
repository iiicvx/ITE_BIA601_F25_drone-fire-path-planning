"""اختبارات الدوال المساعدة للتجارب المستخدمة في دراسة GA (simulation/experiments.py)."""
import numpy as np

from simulation import tune
from simulation.experiments import city_path, run_job, run_jobs
from simulation.quick_run import plot_best_paths, plot_convergence, summary_rows


def test_city_names():
    assert city_path("medium").name == "medium.json" and city_path("medium").exists()
    assert city_path("large_r03").parent.name == "random" and city_path("large_r03").exists()


def test_run_job_and_fitness_overrides():
    a = run_job({"alg": "ga", "city": "small", "seed": 3, "params": {"pop_size": 20}, "budget": 300})
    b = run_job({"alg": "ga", "city": "small", "seed": 3, "params": {"pop_size": 20}, "budget": 300,
                 "fitness": {"init.mode": "uniform"}})
    assert a["fe_used"] == 300 and a["params"]["pop_size"] == 20 and a["job"]["seed"] == 3
    assert a["best_f"] != b["best_f"]                     # التعديل غيّر نقطة البداية فعلًا


def test_parallel_and_serial_give_the_same_results():
    jobs = [{"alg": "ga", "city": "small", "seed": s, "budget": 200} for s in range(2)]
    assert [r["best_f"] for r in run_jobs(jobs, 2)] == [r["best_f"] for r in run_jobs(jobs, 1)]


def test_tuning_jobs_are_one_factor_at_a_time():
    study = {"p_mut": [0.1, 0.25, 1.0], "init.mode": ["uniform", "via"]}
    jobs, defaults = tune.build_jobs("ga", "medium", 2, study, 100)
    tags = {tuple(j["tag"]) for j in jobs}
    assert tags == {("default", "default"), ("p_mut", 0.1), ("p_mut", 1.0), ("init.mode", "uniform")}
    assert len(jobs) == 8 and all(j["seed"] in (1000, 1001) for j in jobs)
    assert next(j for j in jobs if j["tag"] == ["init.mode", "uniform"])["fitness"] == {"init.mode": "uniform"}


def test_tuning_summary_and_figure(tmp_path):
    study = {"p_mut": [0.25, 1.0]}
    jobs, defaults = tune.build_jobs("ga", "small", 2, study, 150)
    rows = tune.summarise(run_jobs(jobs, 1), study, defaults)
    assert [r["value"] for r in rows] == [0.25, 1.0] and rows[0]["is_default"] and rows[0]["runs"] == 2
    tune.plot(rows, "ga", "small", tmp_path / "t.png")
    assert (tmp_path / "t.png").stat().st_size > 10_000


def test_quick_run_outputs(tmp_path):
    res = run_jobs([{"alg": "ga", "city": c, "seed": 0, "budget": 150} for c in ("small", "medium")], 1)
    rows = summary_rows(res)
    assert [r["city"] for r in rows] == ["small", "medium"] and np.isfinite(rows[0]["reference_F"])
    plot_convergence(res, "ga", tmp_path / "c.png")
    plot_best_paths(res, "ga", tmp_path / "p.png")
    assert (tmp_path / "c.png").exists() and (tmp_path / "p.png").exists()


def test_csv_values_are_read_back_with_their_types():
    assert tune._parse("") is None and tune._parse("None") is None and tune._parse("null") is None
    assert tune._parse("40") == 40 and tune._parse("0.25") == 0.25 and tune._parse("ring") == "ring"
