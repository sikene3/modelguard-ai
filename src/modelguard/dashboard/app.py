"""Streamlit operations dashboard over validated monitoring evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from html import escape
from pathlib import Path

import pandas as pd
import streamlit as st
from botocore.exceptions import BotoCoreError, ClientError

from modelguard.dashboard.aws_health import AwsDashboardHealth, DashboardAwsHealthProbe
from modelguard.dashboard.config import DashboardSettings, load_dashboard_settings
from modelguard.dashboard.parsing import DashboardSnapshot, load_dashboard_snapshot
from modelguard.dashboard.presentation import (
    comparable_report_history,
    comparable_signals,
    decision_trend,
    distribution_comparison,
    format_duration,
    format_utc,
    metric_name,
    prediction_score_trend,
    readable_code,
    thresholds_for_signal,
    top_drifting_features,
)
from modelguard.dashboard.repository import (
    DashboardRepository,
    DashboardRepositoryError,
    build_dashboard_repository,
)
from modelguard.monitoring.config import MonitoringConfig, load_monitoring_config
from modelguard.monitoring.report import MonitoringReport


def _inject_styles() -> None:
    st.markdown(
        """
        <style>
        :root { --mg-ink:#132238; --mg-muted:#617084; --mg-panel:#ffffff; --mg-line:#dbe3ea; }
        .stApp { background:linear-gradient(160deg,#f5f8fb 0%,#eef4f7 52%,#f8fafc 100%); }
        .block-container { max-width:1240px; padding-top:4.5rem; padding-bottom:4rem; }
        .stApp h1,.stApp h2,.stApp h3 { color:var(--mg-ink) !important;
            letter-spacing:-.02em; }
        .stApp [data-testid="stMetricLabel"] p,
        .stApp [data-testid="stMetricValue"],
        .stApp [data-testid="stExpander"] summary,
        .stApp [data-testid="stCaptionContainer"] { color:var(--mg-ink) !important; }
        [data-testid="stMetric"] { background:#fff; border:1px solid var(--mg-line);
            border-radius:14px; padding:.8rem 1rem; box-shadow:0 7px 24px rgba(25,45,65,.04); }
        .mg-kicker { color:#087f79; font-weight:750; font-size:.78rem; letter-spacing:.12em;
            text-transform:uppercase; margin-bottom:.25rem; }
        .mg-subtitle { color:var(--mg-muted); font-size:1rem; max-width:800px; margin-top:-.35rem; }
        .mg-snapshot { display:inline-flex; gap:.45rem; align-items:center; margin-top:.5rem;
            padding:.36rem .65rem; border-radius:999px; background:#e7f6f2; color:#126b64;
            font-size:.78rem; font-weight:650; }
        .mg-dot { width:.48rem; height:.48rem; border-radius:50%; background:#1ca58f; }
        .mg-state-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:.85rem;
            margin:.7rem 0 1.35rem; }
        .mg-state { min-height:132px; background:var(--mg-panel); border:1px solid var(--mg-line);
            border-top:5px solid #68788d; border-radius:15px; padding:1rem 1.05rem;
            box-shadow:0 9px 28px rgba(24,47,68,.055); }
        .mg-state-label { color:#66768b; font-size:.72rem; font-weight:800; letter-spacing:.1em;
            text-transform:uppercase; }
        .mg-state-value { color:var(--mg-ink); font-size:1.25rem; font-weight:800;
            margin:.35rem 0 .42rem; line-height:1.2; }
        .mg-state-detail { color:#677487; font-size:.78rem; line-height:1.45; }
        .mg-state.succeeded,.mg-state.valid,.mg-state.healthy { border-top-color:#1b9a73; }
        .mg-state.warning { border-top-color:#d79b1e; }
        .mg-state.degraded,.mg-state.invalid,.mg-state.failed { border-top-color:#d24b55;
            background:#fffafb; }
        .mg-state.stale { border:1px dashed #d88128; border-top:5px solid #d88128;
            background:#fffaf3; }
        .mg-state.insufficient_data { border-top-color:#8559c7; background:#fcfaff; }
        .mg-state.pending_labels { border-top-color:#397dbf; background:#f8fbff; }
        .mg-state.unknown { border:1px dotted #758396; border-top:5px solid #758396;
            background:#f8fafb; }
        .mg-state.unavailable,.mg-state.never_run { border-top-color:#9aa5b1; background:#f6f7f8; }
        .mg-section-note { color:#6a788a; font-size:.86rem; margin-top:-.55rem; }
        .mg-identity { background:#fff; border:1px solid var(--mg-line); border-radius:14px;
            padding:1rem; height:100%; }
        .mg-identity-title { color:#617084; font-weight:800; font-size:.75rem;
            letter-spacing:.08em; text-transform:uppercase; margin-bottom:.6rem; }
        .mg-id-row { display:grid; grid-template-columns:minmax(115px,.8fr) minmax(0,1.6fr);
            gap:.7rem; border-top:1px solid #edf1f4; padding:.46rem 0; font-size:.78rem; }
        .mg-id-row:first-of-type { border-top:0; }
        .mg-id-key { color:#68778a; }
        .mg-id-value { color:#1a2d44; overflow-wrap:anywhere; font-family:ui-monospace,monospace; }
        .mg-equation { background:#eef6f5; color:#164d49; border:1px solid #cfe5e1;
            border-radius:12px; padding:.75rem 1rem; font-family:ui-monospace,monospace;
            font-size:.86rem; margin:.5rem 0 1rem; }
        @media (max-width:900px) {
            .mg-state-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
        }
        @media (max-width:560px) { .block-container { padding:4rem .8rem 3rem; }
            .mg-state-grid { grid-template-columns:1fr; }
            .mg-id-row { grid-template-columns:1fr; gap:.15rem; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _state_card(label: str, value: str, detail: str) -> str:
    css_state = value if value else "unavailable"
    return (
        f'<div class="mg-state {escape(css_state)}">'
        f'<div class="mg-state-label">{escape(label)}</div>'
        f'<div class="mg-state-value">{escape(readable_code(value or "unavailable"))}</div>'
        f'<div class="mg-state-detail">{escape(detail)}</div></div>'
    )


def _run_detail(snapshot: DashboardSnapshot) -> str:
    if snapshot.run_state is None:
        return "Current run evidence cannot be established from the available artifacts."
    if snapshot.run_state.value == "never_run":
        return "No run-status artifact or successful report has been published."
    if snapshot.run_state.value == "failed":
        attempted = snapshot.run_status.latest_attempt_at if snapshot.run_status else None
        reason = snapshot.run_status.failure_reason if snapshot.run_status else None
        return (
            f"Latest attempt {format_utc(attempted)}; reason: {readable_code(reason or 'unknown')}."
        )
    if snapshot.run_state.value == "stale":
        return (
            f"Last success is {format_duration(snapshot.report_age_seconds)} old; configured "
            f"boundary is {format_duration(snapshot.freshness_boundary_seconds)}."
        )
    return f"Latest successful report completed {format_utc(snapshot.report_completed_at)}."


def _render_state_cards(snapshot: DashboardSnapshot) -> None:
    report = snapshot.latest_report
    cards = [
        _state_card(
            "Monitor run",
            snapshot.run_state.value if snapshot.run_state is not None else "unavailable",
            _run_detail(snapshot),
        )
    ]
    if report is None:
        cards.extend(
            _state_card(label, "unavailable", "No validated latest report backs this state.")
            for label in ("Data quality", "Input & prediction drift", "Label-backed performance")
        )
    else:
        cards.extend(
            (
                _state_card(
                    "Data quality",
                    report.states.data_quality.value,
                    "; ".join(
                        readable_code(reason) for reason in report.data_quality.assessment.reasons
                    ),
                ),
                _state_card(
                    "Input & prediction drift",
                    report.states.drift.value,
                    readable_code(report.drift.reason),
                ),
                _state_card(
                    "Label-backed performance",
                    report.states.performance.value,
                    (f"{readable_code(report.performance.reason)}. Never inferred from drift."),
                ),
            )
        )
    st.markdown(
        f'<div class="mg-state-grid">{"".join(cards)}</div>',
        unsafe_allow_html=True,
    )


def _render_issues(snapshot: DashboardSnapshot) -> None:
    for issue in snapshot.issues:
        if issue.severity.value == "error":
            st.error(issue.message, icon="🚫")
        elif issue.severity.value == "warning":
            st.warning(issue.message, icon="⚠️")
        else:
            st.info(issue.message)


def _render_freshness(snapshot: DashboardSnapshot, report: MonitoringReport) -> None:
    st.subheader("Report & data freshness")
    st.markdown(
        '<p class="mg-section-note">Timestamps are the persisted UTC evidence read for this '
        "snapshot—this page does not claim a real-time feed.</p>",
        unsafe_allow_html=True,
    )
    columns = st.columns(4)
    completed_time = (
        snapshot.report_completed_at.strftime("%H:%M:%SZ")
        if snapshot.report_completed_at is not None
        else "Unavailable"
    )
    columns[0].metric("Report completed (UTC)", completed_time)
    columns[1].metric("Report age", format_duration(snapshot.report_age_seconds))
    columns[2].metric("Window age", format_duration(snapshot.window_age_seconds))
    columns[3].metric("Accepted-event age", format_duration(snapshot.accepted_event_age_seconds))
    st.caption(
        f"Report completed at {format_utc(snapshot.report_completed_at)} · "
        f"event-time window: [{format_utc(report.window.start)}, "
        f"{format_utc(report.window.end)}) · "
        f"eligible after {format_utc(report.window.eligible_at)} · "
        f"grace {format_duration(report.window.finalization_grace_seconds)} · "
        "row-level delivery lateness is not claimed."
    )


def _identity_box(title: str, rows: tuple[tuple[str, str], ...]) -> str:
    body = "".join(
        f'<div class="mg-id-row"><div class="mg-id-key">{escape(key)}</div>'
        f'<div class="mg-id-value">{escape(value)}</div></div>'
        for key, value in rows
    )
    return (
        f'<div class="mg-identity"><div class="mg-identity-title">{escape(title)}</div>{body}</div>'
    )


def _render_identities(snapshot: DashboardSnapshot, report: MonitoringReport) -> None:
    st.subheader("Model & evidence identities")
    st.markdown(
        '<p class="mg-section-note">The configured active identity and this report\'s target are '
        "displayed "
        "independently; a model change does not rewrite historical evidence.</p>",
        unsafe_allow_html=True,
    )
    target = report.identities.event_carried_target
    active_rows = (
        (
            (
                "Model version",
                snapshot.active_model.model_version,
            ),
            ("Manifest SHA-256", snapshot.active_model.manifest_sha256),
            ("Input schema SHA-256", snapshot.active_model.input_schema_sha256),
        )
        if snapshot.active_model is not None
        else (("Identity", "Unavailable"),)
    )
    target_rows = (
        ("Model version", target.model_version),
        ("Manifest SHA-256", target.bundle_manifest_sha256),
        ("Event schema", target.event_schema_version),
        ("Input schema", target.input_schema_version),
    )
    left, right = st.columns(2)
    left.markdown(_identity_box("Configured active model", active_rows), unsafe_allow_html=True)
    right.markdown(_identity_box("Report target identity", target_rows), unsafe_allow_html=True)

    baseline = report.identities.baseline_derived_from_verified_manifest
    with st.expander("Baseline, configuration, and report identity", expanded=False):
        identity_frame = pd.DataFrame(
            [
                ("Report ID", report.report_id),
                ("Report schema", report.report_schema_version),
                ("Baseline contract", baseline.baseline_contract_version),
                ("Baseline profile SHA-256", baseline.baseline_profile_sha256),
                ("Baseline input schema SHA-256", baseline.input_schema_sha256),
                ("Training membership SHA-256", baseline.training_membership_sha256),
                ("Training reference rows", str(baseline.training_row_count)),
                ("Monitoring config", report.identities.monitoring_config_version),
                ("Monitoring config SHA-256", report.identities.monitoring_config_hash.digest),
                (
                    "Known non-target identities",
                    str(len(report.identities.known_non_target_identities)),
                ),
            ],
            columns=["Identity", "Recorded value"],
        )
        st.dataframe(identity_frame, hide_index=True, width="stretch")


def _render_reconciliation(report: MonitoringReport) -> None:
    st.subheader("Accepted target volume & exact reconciliation")
    counts = report.records.counts
    st.markdown(
        '<div class="mg-equation">'
        f"{counts.raw:,} raw = {counts.rejected:,} rejected + "
        f"{counts.outside_window:,} outside window + "
        f"{counts.known_non_target:,} known non-target + "
        f"{counts.duplicate:,} duplicate + {counts.accepted_target:,} accepted target ✓</div>",
        unsafe_allow_html=True,
    )
    frame = pd.DataFrame(
        [
            ("Raw records", counts.raw, "Frozen input snapshot"),
            ("Rejected", counts.rejected, "Parse/schema, identity, or conflicting-ID rejection"),
            ("Outside window", counts.outside_window, "Excluded before identity classification"),
            ("Known non-target", counts.known_non_target, "Verified other model identity"),
            ("Duplicate", counts.duplicate, "Identical target event-ID copies excluded"),
            ("Accepted target", counts.accepted_target, "Rows used by this report"),
        ],
        columns=["Exclusive bucket", "Count", "Meaning"],
    )
    st.dataframe(frame, hide_index=True, width="stretch")
    with st.expander("Classification faults and observed identities", expanded=False):
        faults = report.records.faults
        fault_frame = pd.DataFrame(
            [
                ("Parse/schema failures", faults.parse_or_schema_failures),
                ("Unknown identity records", faults.unknown_identity_records),
                ("Conflicting identity records", faults.conflicting_identity_records),
                ("Conflicting event-ID groups", faults.conflicting_event_id_groups),
                ("Conflicting event-ID records", faults.conflicting_event_id_records),
            ],
            columns=["Fault", "Count"],
        )
        st.dataframe(fault_frame, hide_index=True, width="stretch")
        observed = pd.DataFrame(
            [
                {
                    "Classification": item.classification,
                    "Count": item.count,
                    "Model version": item.identity.model_version,
                    "Manifest SHA-256": item.identity.bundle_manifest_sha256,
                }
                for item in report.records.observed_event_carried_identities
            ]
        )
        if not observed.empty:
            st.dataframe(observed, hide_index=True, width="stretch")


def _render_drift_evidence(snapshot: DashboardSnapshot, report: MonitoringReport) -> None:
    st.subheader("Top drifting input features")
    st.markdown(
        '<p class="mg-section-note">Scores, severities, and states come directly from the '
        "immutable monitor report. Thresholds appear only when the exact policy hash matches.</p>",
        unsafe_allow_html=True,
    )
    rows = top_drifting_features(report, snapshot.monitoring_policy)
    frame = pd.DataFrame(
        [
            {
                "Feature": readable_code(row.feature),
                "Metric": row.metric,
                "Score": f"{row.score:.4f}" if row.score is not None else "Not evaluable",
                "Warning threshold": (
                    f"≥ {row.warning_threshold:.3f}"
                    if row.warning_threshold is not None
                    else "Unavailable"
                ),
                "Degraded threshold": (
                    f"≥ {row.degraded_threshold:.3f}"
                    if row.degraded_threshold is not None
                    else "Unavailable"
                ),
                "Severity": readable_code(row.severity),
                "Reason": readable_code(row.reason),
            }
            for row in rows
        ]
    )
    st.dataframe(frame, hide_index=True, width="stretch")

    prediction_signals = [
        signal
        for signal in report.drift.evaluation.signals
        if signal.kind in {"prediction_psi", "decision_js_distance"}
    ]
    if prediction_signals:
        with st.expander("Prediction distribution signals", expanded=True):
            signal_frame = pd.DataFrame(
                [
                    {
                        "Signal": readable_code(signal.name),
                        "Metric": metric_name(signal),
                        "Score": (
                            f"{signal.value:.4f}" if signal.value is not None else "Not evaluable"
                        ),
                        "Warning / degraded": " / ".join(
                            f"{value:.3f}"
                            for value in thresholds_for_signal(
                                signal,
                                snapshot.monitoring_policy,
                            )
                            if value is not None
                        )
                        or "Unavailable",
                        "Severity": readable_code(signal.state.value),
                    }
                    for signal in prediction_signals
                ]
            )
            st.dataframe(signal_frame, hide_index=True, width="stretch")


def _render_distribution_comparisons(report: MonitoringReport) -> None:
    st.subheader("Distribution comparisons")
    numeric = comparable_signals(report, kind="numeric_psi")
    categorical = comparable_signals(report, kind="categorical_js_distance")
    numeric_tab, categorical_tab = st.tabs(["Numeric", "Categorical"])
    with numeric_tab:
        if not numeric:
            st.info("No evaluable numeric comparison is present in this report.")
        else:
            selected_name = st.selectbox(
                "Numeric feature",
                [signal.name for signal in numeric],
                format_func=readable_code,
                key="numeric_distribution_feature",
            )
            signal = next(item for item in numeric if item.name == selected_name)
            st.bar_chart(
                distribution_comparison(signal),
                color=["#9aa8b7", "#168a82"],
                stack=False,
                width="stretch",
            )
            st.caption(
                "Frozen training-reference bins versus accepted target events in the window."
            )
    with categorical_tab:
        if not categorical:
            st.info("No evaluable categorical comparison is present in this report.")
        else:
            selected_name = st.selectbox(
                "Categorical feature",
                [signal.name for signal in categorical],
                format_func=readable_code,
                key="categorical_distribution_feature",
            )
            signal = next(item for item in categorical if item.name == selected_name)
            st.bar_chart(
                distribution_comparison(signal),
                color=["#9aa8b7", "#168a82"],
                stack=False,
                width="stretch",
            )
            st.caption("The full category universe includes explicit other and missing buckets.")


def _render_prediction_trends(
    snapshot: DashboardSnapshot,
    report: MonitoringReport,
) -> None:
    st.subheader("Prediction score & decision trend")
    st.markdown(
        '<p class="mg-section-note">Exact per-report distribution proportions across immutable '
        "windows; these charts are not label-backed performance evidence.</p>",
        unsafe_allow_html=True,
    )
    history = comparable_report_history(snapshot.recent_reports, reference=report)
    excluded_count = len(snapshot.recent_reports) - len(history)
    if excluded_count:
        st.caption(
            f"{excluded_count} recent report(s) with a different target, baseline, or monitoring "
            "policy identity are excluded from these comparisons."
        )
    score, decisions = st.tabs(["Prediction score bins", "Locked decisions"])
    score_frame = prediction_score_trend(history)
    with score:
        if score_frame.empty:
            st.info("No comparable prediction-score history is available.")
        elif len(history) == 1:
            st.bar_chart(score_frame, stack=True, width="stretch")
            st.caption(
                "One comparable report is available; the chart is a distribution snapshot, "
                "not yet a time trend."
            )
        else:
            st.area_chart(score_frame, width="stretch")
    decision_frame = decision_trend(history)
    with decisions:
        if decision_frame.empty:
            st.info("No comparable decision history is available.")
        elif len(history) == 1:
            st.bar_chart(decision_frame, stack=True, width="stretch")
            st.caption(
                "One comparable report is available; the chart is a decision snapshot, "
                "not yet a time trend."
            )
        else:
            st.line_chart(decision_frame, width="stretch")


def _render_missingness(report: MonitoringReport) -> None:
    with st.expander("Separate missingness evidence", expanded=False):
        frame = pd.DataFrame(
            [
                {
                    "Feature": readable_code(signal.feature),
                    "Baseline rate": signal.baseline_rate,
                    "Current rate": signal.current_rate,
                    "Absolute delta": signal.absolute_delta,
                    "Quality": signal.state,
                }
                for signal in report.drift.evaluation.missingness
            ]
        )
        st.dataframe(frame, hide_index=True, width="stretch")


def _render_performance(report: MonitoringReport) -> None:
    st.subheader("Label-backed performance evidence")
    performance = report.performance
    st.caption(
        f"Scope: {performance.interpretation}. {performance.limitation.capitalize()}. "
        "Drift never substitutes for labels."
    )
    if performance.metrics is None:
        if performance.state.value == "pending_labels":
            st.warning(
                "A label source is configured, but the labeled subset does not meet every "
                "adequacy requirement. No performance state is inferred from drift."
            )
        else:
            st.info(
                "No label-backed metrics are available for this report. No accuracy or "
                "performance conclusion is shown."
            )
    else:
        metrics = performance.metrics
        columns = st.columns(4)
        columns[0].metric("Labeled rows", f"{metrics.row_count:,}")
        columns[1].metric("Average precision", f"{metrics.average_precision:.3f}")
        columns[2].metric("Labeled prevalence", f"{metrics.prevalence:.3f}")
        columns[3].metric("Synthetic cost delta", f"{metrics.synthetic_cost_delta:+.3f}")
        st.caption(
            "The synthetic cost delta compares only the labeled subset at the locked threshold "
            "with the held-out synthetic reference; it is not a significance test or causal claim."
        )
    counts = performance.counts
    coverage = "Unavailable" if performance.coverage is None else f"{performance.coverage:.1%}"
    with st.expander("Label coverage and adequacy", expanded=False):
        st.write(
            {
                "label_source_configured": performance.label_source_configured,
                "coverage": coverage,
                "joined": counts.joined,
                "missing": counts.missing,
                "orphan": counts.orphan,
                "rejected": counts.rejected,
                "duplicate": counts.duplicate,
                "conflicting": counts.conflicting,
                "requirements": performance.adequacy_requirements,
            }
        )


def _render_report_access(
    repository: DashboardRepository,
    snapshot: DashboardSnapshot,
    report: MonitoringReport,
) -> None:
    st.subheader("Immutable incident report")
    try:
        access = repository.html_report_access(
            report_id=report.report_id,
            window_end=report.window.end,
            now=snapshot.captured_at,
        )
    except DashboardRepositoryError:
        st.warning("The HTML report could not be accessed from the configured repository.")
        return
    if access is None:
        st.warning("The validated JSON report has no corresponding HTML artifact.")
    elif access.content is not None:
        st.download_button(
            "Download offline HTML report",
            data=access.content,
            file_name=access.filename,
            mime="text/html",
            type="primary",
        )
        st.caption("Local mode returns the immutable offline report as a browser download.")
    elif access.url is not None:
        st.link_button("Download via short-lived HTTPS link", access.url, type="primary")
        st.caption(
            f"AWS mode keeps the bucket private and issues a temporary link expiring at "
            f"{format_utc(access.expires_at)}. The URL is not persisted or logged by the dashboard."
        )


def _render_dashboard(
    settings: DashboardSettings,
    repository: DashboardRepository,
    snapshot: DashboardSnapshot,
    aws_health: AwsDashboardHealth | None = None,
) -> None:
    st.markdown(
        '<div class="mg-kicker">Read-only operations evidence</div>', unsafe_allow_html=True
    )
    st.title("ModelGuard AI")
    st.markdown(
        '<p class="mg-subtitle">System health, exact model identity, data quality, distribution '
        "change, and label-backed evidence—kept deliberately separate.</p>",
        unsafe_allow_html=True,
    )
    if aws_health is not None:
        source_summary = ", ".join(
            f"{source.source}={source.state.value}" for source in aws_health.sources
        )
        if aws_health.state.value == "healthy":
            st.success(
                f"AWS evidence sources are reachable in {aws_health.region}: {source_summary}."
            )
        else:
            st.warning(
                f"AWS evidence-source health is {aws_health.state.value}; no healthy runtime "
                f"claim is inferred. {source_summary}."
            )
    st.markdown(
        '<div class="mg-snapshot"><span class="mg-dot"></span>'
        f"Snapshot read {escape(format_utc(snapshot.captured_at))} · "
        f"{escape(settings.dashboard_repository.value)} repository</div>",
        unsafe_allow_html=True,
    )
    _render_issues(snapshot)
    _render_state_cards(snapshot)
    report = snapshot.latest_report
    if report is None:
        st.info(
            "Dashboard sections that require a validated monitoring report are intentionally "
            "withheld. Publish or repair the report artifacts, then refresh this page."
        )
        return
    _render_freshness(snapshot, report)
    _render_identities(snapshot, report)
    _render_reconciliation(report)
    _render_drift_evidence(snapshot, report)
    _render_missingness(report)
    _render_distribution_comparisons(report)
    _render_prediction_trends(snapshot, report)
    _render_performance(report)
    _render_report_access(repository, snapshot, report)
    with st.expander("Interpretation limits", expanded=False):
        for limitation in report.limitations:
            st.markdown(f"- {limitation}")


def _load_policy(path: Path) -> tuple[MonitoringConfig | None, str | None]:
    try:
        return load_monitoring_config(path), None
    except FileNotFoundError:
        return None, "missing artifact"
    except OSError:
        return None, "unreadable artifact"
    except ValueError:
        return None, "malformed artifact"


def main() -> None:
    st.set_page_config(
        page_title="ModelGuard AI · Operations",
        page_icon="🛡️",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    _inject_styles()
    try:
        settings = load_dashboard_settings()
    except ValueError:
        st.error(
            "Dashboard configuration is invalid. No repository access was attempted; review the "
            "documented dashboard environment contract."
        )
        return
    policy, policy_problem = _load_policy(settings.monitoring_config_path)
    try:
        repository = build_dashboard_repository(settings)
    except (ValueError, DashboardRepositoryError):
        st.error("Dashboard repository configuration is invalid; no evidence was loaded.")
        return
    snapshot = load_dashboard_snapshot(
        repository,
        expected_active_model_version=settings.active_model_version,
        monitoring_policy=policy,
        captured_at=datetime.now(UTC),
        history_limit=settings.dashboard_history_limit,
        policy_problem=policy_problem,
    )
    aws_health: AwsDashboardHealth | None = None
    if settings.aws_health_required:
        try:
            aws_health = DashboardAwsHealthProbe(settings).probe()
        except (BotoCoreError, ClientError, TimeoutError, ValueError):
            st.error("AWS source-health verification failed closed; no healthy claim is available.")
    _render_dashboard(settings, repository, snapshot, aws_health)


if __name__ == "__main__":
    main()
