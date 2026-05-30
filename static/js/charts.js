// FlowWatch Charts Engine (Phase 19)

let riskDoughnutInstance = null;
let trendLineInstance = null;

document.addEventListener('DOMContentLoaded', () => {
    // 1. Initialize Risk Distribution Doughnut Chart
    initRiskDoughnutChart();
});

/**
 * Initializes the Doughnut Chart showing High, Medium, and Low risk cohort distribution.
 */
function initRiskDoughnutChart() {
    const chartContainer = document.getElementById('risk-doughnut-container');
    if (!chartContainer) return;
    
    const canvas = document.getElementById('riskDoughnutChart');
    if (!canvas) return;
    
    // Retrieve metrics from data attributes
    const high = parseInt(chartContainer.getAttribute('data-high') || '0', 10);
    const medium = parseInt(chartContainer.getAttribute('data-medium') || '0', 10);
    const low = parseInt(chartContainer.getAttribute('data-low') || '0', 10);
    
    // Show fallback text if no data exists
    if (high === 0 && medium === 0 && low === 0) {
        chartContainer.innerHTML = '<p class="no-data-msg" style="color: var(--text-muted); font-size: 0.9rem;">Upload a CSV to view risk distributions.</p>';
        return;
    }
    
    const ctx = canvas.getContext('2d');
    
    if (riskDoughnutInstance) {
        riskDoughnutInstance.destroy();
    }
    
    riskDoughnutInstance = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: ['High Risk', 'Medium Risk', 'Low Risk'],
            datasets: [{
                data: [high, medium, low],
                backgroundColor: [
                    'rgba(239, 68, 68, 0.75)',   // Neon Red
                    'rgba(245, 158, 11, 0.75)',   // Yellow-Orange
                    'rgba(16, 185, 129, 0.75)'    // Emerald Green
                ],
                borderColor: [
                    '#ef4444',
                    '#f59e0b',
                    '#10b981'
                ],
                borderWidth: 1.5,
                hoverOffset: 6
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: {
                        color: '#f3f4f6',
                        font: {
                            family: "'Outfit', sans-serif",
                            size: 11
                        },
                        padding: 15
                    }
                },
                tooltip: {
                    backgroundColor: 'rgba(10, 10, 20, 0.95)',
                    titleColor: '#ffffff',
                    bodyColor: '#e5e7eb',
                    borderColor: 'rgba(255, 255, 255, 0.1)',
                    borderWidth: 1,
                    padding: 10,
                    callbacks: {
                        label: function(context) {
                            const total = context.dataset.data.reduce((a, b) => a + b, 0);
                            const val = context.raw;
                            const percentage = total > 0 ? Math.round((val / total) * 100) : 0;
                            return ` ${context.label}: ${val} (${percentage}%)`;
                        }
                    }
                }
            },
            cutout: '68%'
        }
    });
}

/**
 * Fetches student history from API and renders a dual-axis trend line chart.
 * @param {string} studentId - Unique identifier of the student
 */
function loadStudentTrendChart(studentId) {
    const container = document.getElementById('student-trend-chart-container');
    if (!container) return;
    
    // Clear loading state or placeholders
    container.innerHTML = '<canvas id="studentTrendChart"></canvas>';
    const canvas = document.getElementById('studentTrendChart');
    const ctx = canvas.getContext('2d');
    
    fetch(`/api/student/${studentId}/history`)
        .then(response => {
            if (!response.ok) throw new Error('Network failed to fetch history');
            return response.json();
        })
        .then(data => {
            if (!data || data.length === 0) {
                container.innerHTML = '<p class="no-data-msg" style="color: var(--text-muted);">No history logged for this student.</p>';
                return;
            }
            
            // Extract axes
            const weeks = data.map(d => `Week ${d.week_number}`);
            const engagementScores = data.map(d => d.composite_engagement);
            const quizScores = data.map(d => d.avg_quiz_score);
            const riskScores = data.map(d => d.risk_score);
            
            if (trendLineInstance) {
                trendLineInstance.destroy();
            }
            
            trendLineInstance = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: weeks,
                    datasets: [
                        {
                            label: 'Engagement Score',
                            data: engagementScores,
                            borderColor: '#6366f1', // Neon Indigo
                            backgroundColor: 'rgba(99, 102, 241, 0.05)',
                            borderWidth: 2.5,
                            tension: 0.4,
                            fill: true,
                            yAxisID: 'y'
                        },
                        {
                            label: 'Quiz Average',
                            data: quizScores,
                            borderColor: '#a855f7', // Neon Purple
                            backgroundColor: 'transparent',
                            borderWidth: 2,
                            borderDash: [5, 5],
                            tension: 0.4,
                            yAxisID: 'y1'
                        },
                        {
                            label: 'Risk Threat Level',
                            data: riskScores,
                            borderColor: '#ef4444', // Neon Red
                            backgroundColor: 'transparent',
                            borderWidth: 1.5,
                            tension: 0.3,
                            yAxisID: 'y'
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        x: {
                            grid: {
                                color: 'rgba(255, 255, 255, 0.03)'
                            },
                            ticks: {
                                color: '#9ca3af',
                                font: { family: "'Inter', sans-serif" }
                            }
                        },
                        y: {
                            type: 'linear',
                            display: true,
                            position: 'left',
                            title: {
                                display: true,
                                text: 'Engagement & Risk (0-100)',
                                color: '#f3f4f6'
                            },
                            grid: {
                                color: 'rgba(255, 255, 255, 0.04)'
                            },
                            ticks: {
                                color: '#9ca3af',
                                font: { family: "'Inter', sans-serif" }
                            },
                            min: 0,
                            max: 100
                        },
                        y1: {
                            type: 'linear',
                            display: true,
                            position: 'right',
                            title: {
                                display: true,
                                text: 'Quiz Grade (0.0-1.0)',
                                color: '#f3f4f6'
                            },
                            grid: {
                                drawOnChartArea: false // prevent grid overlap
                            },
                            ticks: {
                                color: '#9ca3af',
                                font: { family: "'Inter', sans-serif" }
                            },
                            min: 0.0,
                            max: 1.0
                        }
                    },
                    plugins: {
                        legend: {
                            labels: {
                                color: '#f3f4f6',
                                font: { family: "'Outfit', sans-serif", size: 11 }
                            }
                        },
                        tooltip: {
                            backgroundColor: 'rgba(10, 10, 20, 0.95)',
                            titleColor: '#ffffff',
                            bodyColor: '#e5e7eb',
                            borderColor: 'rgba(255, 255, 255, 0.1)',
                            borderWidth: 1,
                            padding: 10
                        }
                    }
                }
            });
        })
        .catch(err => {
            console.error('Trend chart fetch failure:', err);
            container.innerHTML = `<p class="no-data-msg" style="color: var(--color-error);">Failed to load performance charts: ${err.message}</p>`;
        });
}
