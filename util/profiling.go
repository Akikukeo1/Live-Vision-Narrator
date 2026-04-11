package util

import (
	"fmt"
	"time"
)

// ProfilePoint records a timing checkpoint
type ProfilePoint struct {
	Name      string
	TimeMs    float64
	Timestamp time.Time
}

// Profiler tracks timing for specific operations
type Profiler struct {
	start   time.Time
	points  []ProfilePoint
	enabled bool
}

// NewProfiler creates a new profiler
func NewProfiler(enabled bool) *Profiler {
	return &Profiler{
		start:   time.Now(),
		points:  []ProfilePoint{},
		enabled: enabled,
	}
}

// Mark records a timing checkpoint
func (p *Profiler) Mark(name string) {
	if !p.enabled {
		return
	}
	elapsed := time.Since(p.start).Seconds() * 1000 // Convert to ms
	p.points = append(p.points, ProfilePoint{
		Name:      name,
		TimeMs:    elapsed,
		Timestamp: time.Now(),
	})
}

// GetDelta returns the time elapsed between two marks
func (p *Profiler) GetDelta(from, to string) float64 {
	if !p.enabled {
		return 0
	}
	var fromTime, toTime float64
	found1, found2 := false, false

	for _, pt := range p.points {
		if pt.Name == from {
			fromTime = pt.TimeMs
			found1 = true
		}
		if pt.Name == to {
			toTime = pt.TimeMs
			found2 = true
		}
	}

	if found1 && found2 {
		return toTime - fromTime
	}
	return 0
}

// PrintSummary returns a formatted summary of all marks
func (p *Profiler) PrintSummary() string {
	if !p.enabled || len(p.points) == 0 {
		return ""
	}

	summary := "Profile: "
	for i, pt := range p.points {
		if i == 0 {
			summary += fmt.Sprintf("%s=%.2fms", pt.Name, pt.TimeMs)
		} else {
			delta := pt.TimeMs - p.points[i-1].TimeMs
			summary += fmt.Sprintf(" → %s(+%.2fms)", pt.Name, delta)
		}
	}
	return summary
}
