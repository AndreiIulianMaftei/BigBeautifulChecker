import React, { useEffect, useMemo, useRef, useState } from 'react';
import Plot from 'react-plotly.js';
import { motion, AnimatePresence } from 'framer-motion';
import { AreaChart, Area, BarChart, Bar, LineChart, Line, PieChart, Pie, Cell, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import './App.css';

const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';
const COST_HORIZONS = [5, 10, 15];

const formatCurrency = (value) => {
  const formatter = new Intl.NumberFormat('de-CH', {
    style: 'currency',
    currency: 'EUR',
    maximumFractionDigits: 0,
  });
  return formatter.format(Math.max(0, value || 0));
};

const clampSeverity = (value) => {
  const numeric = parseInt(value, 10);
  if (Number.isNaN(numeric)) {
    return 3;
  }
  return Math.min(5, Math.max(1, numeric));
};

const buildCostProfilesFromPricing = (pricing) => {
  if (!pricing?.analyses?.length) {
    return [];
  }

  return pricing.analyses.map((analysis, analysisIndex) => {
    const yearlySeries = Array.from({ length: 15 }, (_, index) => {
      const year = index + 1;
      const backendRow = (analysis.ten_year_projection?.yearly_costs || []).find(
        (entry) => Number(entry.year) === year
      );

      return {
        year,
        cost: backendRow ? Number(backendRow.cost) || 0 : 0,
        scheduled_work: backendRow?.scheduled_work || backendRow?.notes || 'No work scheduled',
      };
    });

    const horizons = COST_HORIZONS.map((year) => ({
      year,
      total: yearlySeries
        .filter((entry) => entry.year <= year)
        .reduce((sum, entry) => sum + entry.cost, 0),
    }));

    const maxHorizon = Math.max(...horizons.map((h) => h.total), 1);
    const maxYearly = Math.max(...yearlySeries.map((entry) => entry.cost), 1);

    return {
      label: analysis.damage_item || `Detected system ${analysisIndex + 1}`,
      severity: analysis.severity ?? 3,
      category: analysis.complete_data?.Category || 'Building component',
      horizons,
      yearlySeries,
      maxHorizon,
      maxYearly,
      summary: analysis.ten_year_projection?.summary || 'No major maintenance expected.',
    };
  });
};

const buildAggregateReport = (images) => {
  if (!images.length) {
    return null;
  }

  const totals = COST_HORIZONS.map((year) => ({
    year,
    total: images.reduce((imageSum, image) => {
      return (
        imageSum +
        (image.costProfiles || []).reduce((profileSum, profile) => {
          const horizon = profile.horizons.find((h) => h.year === year);
          return profileSum + (horizon?.total || 0);
        }, 0)
      );
    }, 0),
  }));

  const combinedSystems = {};
  images.forEach((image) => {
    (image.costProfiles || []).forEach((profile) => {
      const fifteenYear = profile.horizons.find((h) => h.year === 15)?.total || 0;
      combinedSystems[profile.label] = (combinedSystems[profile.label] || 0) + fifteenYear;
    });
  });

  const topSystems = Object.entries(combinedSystems)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3)
    .map(([label, value]) => ({ label, value }));

  return { totals, topSystems };
};

function App() {
  const [isTransitioning, setIsTransitioning] = useState(false);
  const [showUpload, setShowUpload] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');
  const [processedImages, setProcessedImages] = useState([]);
  const [showResults, setShowResults] = useState(false);
  const [selectedImageId, setSelectedImageId] = useState(null);
  const [propertyAddress, setPropertyAddress] = useState('');
  const [propertyPrice, setPropertyPrice] = useState('');
  const [propertyType, setPropertyType] = useState('APARTMENTBUY');
  const [valuationReport, setValuationReport] = useState(null);
  const [valuationError, setValuationError] = useState('');
  const [isValuationLoading, setIsValuationLoading] = useState(false);
  const [pendingFiles, setPendingFiles] = useState([]);
  const [showCameraModal, setShowCameraModal] = useState(false);
  const [cameraStream, setCameraStream] = useState(null);
  const [selectedHorizonYear, setSelectedHorizonYear] = useState(null);
  const [selectedSystemName, setSelectedSystemName] = useState(null);
  const fileInputRef = useRef(null);
  const videoRef = useRef(null);
  const canvasRef = useRef(null);

  const selectedImage = useMemo(
    () => processedImages.find((image) => image.id === selectedImageId) || null,
    [processedImages, selectedImageId]
  );

  const aggregateReport = useMemo(() => buildAggregateReport(processedImages), [processedImages]);
  const tenYearRepairBudget = useMemo(() => {
    if (!aggregateReport) {
      return 0;
    }
    const tenYear = aggregateReport.totals.find((total) => total.year === 10);
    return tenYear?.total || 0;
  }, [aggregateReport]);

  // Prepare detailed horizon data for modal
  const horizonModalData = useMemo(() => {
    if (!selectedHorizonYear || !aggregateReport) return null;

    const horizon = aggregateReport.totals.find(t => t.year === selectedHorizonYear);
    if (!horizon) return null;

    // Collect all cost profiles up to this year
    const yearlyBreakdown = Array.from({ length: selectedHorizonYear }, (_, i) => {
      const year = i + 1;
      let totalCost = 0;
      const systems = {};

      processedImages.forEach(image => {
        (image.costProfiles || []).forEach(profile => {
          const yearData = profile.yearlySeries.find(entry => entry.year === year);
          if (yearData && yearData.cost > 0) {
            totalCost += yearData.cost;
            if (!systems[profile.label]) {
              systems[profile.label] = 0;
            }
            systems[profile.label] += yearData.cost;
          }
        });
      });

      return {
        year,
        totalCost,
        systems: Object.entries(systems).map(([name, cost]) => ({ name, cost }))
      };
    });

    // Calculate cumulative costs by system
    const systemCumulative = {};
    processedImages.forEach(image => {
      (image.costProfiles || []).forEach(profile => {
        const totalForHorizon = profile.yearlySeries
          .filter(entry => entry.year <= selectedHorizonYear)
          .reduce((sum, entry) => sum + entry.cost, 0);
        
        if (totalForHorizon > 0) {
          systemCumulative[profile.label] = (systemCumulative[profile.label] || 0) + totalForHorizon;
        }
      });
    });

    const systemBreakdown = Object.entries(systemCumulative)
      .map(([name, value]) => ({ name, value }))
      .sort((a, b) => b.value - a.value);

    return {
      year: selectedHorizonYear,
      total: horizon.total,
      yearlyBreakdown,
      systemBreakdown
    };
  }, [selectedHorizonYear, aggregateReport, processedImages]);

  // Prepare detailed system data for modal
  const systemModalData = useMemo(() => {
    if (!selectedSystemName || !processedImages.length) return null;

    // Collect all instances of this system across images
    const systemInstances = [];
    processedImages.forEach((image, imgIdx) => {
      (image.costProfiles || []).forEach(profile => {
        if (profile.label === selectedSystemName) {
          systemInstances.push({
            imageIndex: imgIdx,
            imageName: image.fileName,
            profile,
            severity: profile.severity,
            category: profile.category
          });
        }
      });
    });

    if (systemInstances.length === 0) return null;

    // Aggregate yearly costs across all instances
    const yearlyData = Array.from({ length: 15 }, (_, i) => {
      const year = i + 1;
      let totalCost = 0;
      const instances = [];

      systemInstances.forEach(instance => {
        const yearEntry = instance.profile.yearlySeries.find(e => e.year === year);
        if (yearEntry && yearEntry.cost > 0) {
          totalCost += yearEntry.cost;
          instances.push({
            imageName: instance.imageName,
            cost: yearEntry.cost,
            work: yearEntry.scheduled_work
          });
        }
      });

      return { year, totalCost, instances };
    });

    // Calculate cumulative by instance
    const instanceBreakdown = systemInstances.map(instance => {
      const total15Year = instance.profile.horizons.find(h => h.year === 15)?.total || 0;
      return {
        imageName: instance.imageName,
        total: total15Year,
        severity: instance.severity,
        category: instance.category,
        yearlySeries: instance.profile.yearlySeries
      };
    });

    const total15Year = instanceBreakdown.reduce((sum, inst) => sum + inst.total, 0);
    const avgSeverity = systemInstances.reduce((sum, inst) => sum + inst.severity, 0) / systemInstances.length;

    return {
      systemName: selectedSystemName,
      totalCost: total15Year,
      instanceCount: systemInstances.length,
      averageSeverity: Math.round(avgSeverity),
      yearlyData,
      instanceBreakdown,
      category: systemInstances[0]?.category || 'System'
    };
  }, [selectedSystemName, processedImages]);

  const plotlyFigure = useMemo(() => {
    if (!selectedImage?.costProfiles?.length) {
      return null;
    }

    const traces = selectedImage.costProfiles.map((profile) => {
      let cumulative = 0;
      const x = [];
      const y = [];
      const hover = [];
      profile.yearlySeries.forEach((entry) => {
        cumulative += entry.cost;
        x.push(entry.year);
        y.push(Number(cumulative.toFixed(2)));
        hover.push(
          `Year ${entry.year}<br>${profile.label}<br>` +
            `Added: ${formatCurrency(entry.cost)}<br>${entry.scheduled_work}`
        );
      });
      return {
        x,
        y,
        mode: 'lines+markers',
        name: profile.label,
        line: { width: 3 },
        marker: { size: 6 },
        hovertemplate: '%{customdata}<extra></extra>',
        customdata: hover,
      };
    });

    const layout = {
      margin: { l: 50, r: 20, t: 10, b: 40 },
      xaxis: { title: 'Year', dtick: 1, range: [1, 15] },
      yaxis: { title: 'Cumulative cost (EUR)', rangemode: 'tozero' },
      showlegend: true,
      legend: { orientation: 'h', y: -0.2 },
      hovermode: 'x unified',
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: 'rgba(0,0,0,0)',
    };

    const config = {
      displaylogo: false,
      responsive: true,
      modeBarButtonsToRemove: ['lasso2d', 'select2d'],
    };

    return { data: traces, layout, config };
  }, [selectedImage]);

  const handleStartClick = () => {
    setIsTransitioning(true);
    setTimeout(() => {
      setShowUpload(true);
    }, 800);
  };

  useEffect(() => {
    if (processedImages.length > 0) {
      const timeout = setTimeout(() => setShowResults(true), 300);
      return () => clearTimeout(timeout);
    }
  }, [processedImages.length]);

  const handleViewUpload = () => {
    setShowResults(false);
    setSelectedImageId(null);
  };

  const handleOpenDetail = (imageId) => {
    setSelectedImageId(imageId);
  };

  const handleCloseDetail = () => {
    setSelectedImageId(null);
  };

  const uploadFile = async (file) => {
    const data = new FormData();
    data.append('file', file);

    const response = await fetch(`${API_BASE_URL}/detect-and-price`, {
      method: 'POST',
      body: data,
    });

    if (!response.ok) {
      const detail = await response.text();
      throw new Error(detail || 'Failed to process file');
    }

    const payload = await response.json();
    const detection = payload?.detection || {};
    const annotations = detection?.annotation || [];
    const pricing = payload?.pricing;
    const costProfiles = buildCostProfilesFromPricing(pricing);

    return {
      id: `${file.name}-${Date.now()}`,
      fileName: file.name,
      annotations,
      detectedCategory: detection?.detected_category,
      imageSrc: payload?.annotated_image_base64
        ? `data:image/png;base64,${payload.annotated_image_base64}`
        : null,
      pricing,
      costProfiles,
    };
  };

  const handleFileSelection = (files) => {
    if (!files.length) {
      return;
    }

    setErrorMessage('');
    setPendingFiles((prev) => [...prev, ...files]);
  };

  const handleFileInputChange = (event) => {
    handleFileSelection(Array.from(event.target.files || []));
    if (event.target) {
      event.target.value = '';
    }
  };

  const handleOpenCamera = async () => {
    const numericPrice = parseFloat(propertyPrice);
    if (!propertyAddress.trim() || Number.isNaN(numericPrice)) {
      setErrorMessage('Please enter the property address and price before taking photos.');
      return;
    }
    
    setShowCameraModal(true);
    setErrorMessage('');
    
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ 
        video: { 
          facingMode: 'environment',
          width: { ideal: 1920 },
          height: { ideal: 1080 }
        } 
      });
      
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        videoRef.current.play();
        setCameraStream(stream);
      }
    } catch (error) {
      console.error('Camera error:', error);
      let errorMsg = 'Unable to access camera. ';
      if (error.name === 'NotAllowedError' || error.name === 'PermissionDeniedError') {
        errorMsg += 'Please allow camera permissions in your browser settings.';
      } else if (error.name === 'NotFoundError') {
        errorMsg += 'No camera found on this device.';
      } else if (error.name === 'NotReadableError') {
        errorMsg += 'Camera is already in use by another application.';
      } else {
        errorMsg += error.message || 'Please check permissions.';
      }
      setErrorMessage(errorMsg);
      setShowCameraModal(false);
    }
  };

  const handleCapturePhoto = async () => {
    try {
      if (!videoRef.current || !canvasRef.current) {
        throw new Error('Video or canvas not ready');
      }

      const video = videoRef.current;
      const canvas = canvasRef.current;
      
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      
      const context = canvas.getContext('2d');
      context.drawImage(video, 0, 0, canvas.width, canvas.height);
      
      // Convert canvas to blob
      const blob = await new Promise((resolve) => {
        canvas.toBlob(resolve, 'image/jpeg', 0.95);
      });
      
      const file = new File([blob], `camera-${Date.now()}.jpg`, { type: 'image/jpeg' });
      
      setIsUploading(true);
      handleCloseCamera();
      
      const uploadResult = await uploadFile(file);
      setProcessedImages((prev) => [uploadResult, ...prev]);
      setErrorMessage('');
    } catch (error) {
      console.error('Capture error:', error);
      setErrorMessage(error.message || 'Unable to capture photo.');
    } finally {
      setIsUploading(false);
    }
  };

  const handleCloseCamera = () => {
    if (cameraStream) {
      cameraStream.getTracks().forEach(track => track.stop());
      setCameraStream(null);
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
    setShowCameraModal(false);
  };

  const handleProcessQueuedFiles = async () => {
    if (!pendingFiles.length) {
      setErrorMessage('Add photos first, then start processing.');
      return;
    }

    const numericPrice = parseFloat(propertyPrice);
    if (!propertyAddress.trim() || Number.isNaN(numericPrice)) {
      setErrorMessage('Please enter the property address and price before processing.');
      return;
    }

    setErrorMessage('');
    setIsUploading(true);

    try {
      const uploadResults = await Promise.all(pendingFiles.map(uploadFile));
      setProcessedImages((prev) => [...uploadResults, ...prev]);
      setPendingFiles([]);
    } catch (error) {
      console.error('Upload error:', error);
      setErrorMessage(error.message || 'Unable to process the selected files.');
    } finally {
      setIsUploading(false);
    }
  };

  const handleUploadAreaDrop = (event) => {
    event.preventDefault();
    const files = Array.from(event.dataTransfer.files || []);
    handleFileSelection(files);
  };

  const fetchValuationReport = async (damageItems) => {
    setIsValuationLoading(true);
    setValuationError('');
    try {
      const numericPrice = parseFloat(propertyPrice);
      const response = await fetch(`${API_BASE_URL}/valuation-report`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          address: propertyAddress,
          current_price: numericPrice,
          property_type: propertyType,
          damage_items: damageItems,
          use_mock: false,
          max_concurrent: 5,
        }),
      });

      if (!response.ok) {
        const detail = await response.text();
        throw new Error(detail || 'Failed to generate valuation report');
      }

      const payload = await response.json();
      setValuationReport(payload);
    } catch (err) {
      console.error('Valuation error:', err);
      setValuationError(err.message || 'Unable to build valuation report.');
      setValuationReport(null);
    } finally {
      setIsValuationLoading(false);
    }
  };

  useEffect(() => {
    if (!processedImages.length) {
      setValuationReport(null);
      return;
    }

    const numericPrice = parseFloat(propertyPrice);
    if (!propertyAddress.trim() || Number.isNaN(numericPrice)) {
      return;
    }

    const aggregatedDamage = processedImages.flatMap((image) =>
      (image.pricing?.analyses || []).map((analysis) => ({
        item: analysis.damage_item || 'Damage',
        severity: clampSeverity(analysis.severity ?? 3),
      }))
    );

    if (!aggregatedDamage.length) {
      return;
    }

    fetchValuationReport(aggregatedDamage);
  }, [processedImages, propertyAddress, propertyPrice, propertyType]);

  return (
    <div className="app">
      <img 
        src="/12312Asset 1qww21312312.svg" 
        alt="Background" 
        className="background"
      />
      
      <div className={`landing-content ${isTransitioning ? 'slide-up' : ''}`}>
        <img 
          src="/12312Asset 2qww21312312.svg" 
          alt="Crib Checker" 
          className="title"
        />
        
        <img 
          src="/12312Asset 3qww21312312.svg" 
          alt="Start now" 
          className="button"
          onClick={handleStartClick}
        />
      </div>

      <div className={`upload-section ${showUpload && !showResults ? 'show' : ''}`}>
        <div className="upload-container">
          <div className="upload-header">
            <p className="eyebrow">Step 1</p>
            <h2>Upload inspection photos</h2>
            <p className="subtitle">Drag and drop multiple images or browse your computer.</p>
          </div>

          <div className="property-form">
            <div className="property-field">
              <label htmlFor="property-address">Property address</label>
              <input
                id="property-address"
                type="text"
                placeholder="e.g. Munich, Bavaria"
                value={propertyAddress}
                onChange={(e) => setPropertyAddress(e.target.value)}
              />
            </div>
            <div className="property-field">
              <label htmlFor="property-price">Purchase price (EUR)</label>
              <input
                id="property-price"
                type="number"
                min="0"
                placeholder="550000"
                value={propertyPrice}
                onChange={(e) => setPropertyPrice(e.target.value)}
              />
            </div>
            <div className="property-field">
              <label htmlFor="property-type">Property type</label>
              <select
                id="property-type"
                value={propertyType}
                onChange={(e) => setPropertyType(e.target.value)}
              >
                <option value="APARTMENTBUY">Apartment</option>
                <option value="HOUSEBUY">House</option>
                <option value="LANDBUY">Land</option>
                <option value="GARAGEBUY">Garage</option>
                <option value="OFFICEBUY">Office</option>
              </select>
            </div>
          </div>
          
          <div
            className="upload-area"
            onClick={() => fileInputRef.current?.click()}
            onDragOver={(event) => event.preventDefault()}
            onDrop={handleUploadAreaDrop}
          >
            <input
              ref={fileInputRef}
              type="file"
              id="file-upload"
              multiple
              accept="image/*,.pdf"
              onChange={handleFileInputChange}
              className="file-input"
            />
            <div className="upload-label">
              <p className="upload-text">Drop your files here</p>
              <p className="upload-formats">JPEG or PNG, up to 50MB each</p>
              <button
                type="button"
                className="browse-button"
                onClick={(event) => {
                  event.stopPropagation();
                  fileInputRef.current?.click();
                }}
              >
                Browse files
              </button>
              <p className="upload-hint">You can select multiple files at once or snap a new photo.</p>
            </div>
          </div>

          <div className="upload-actions">
            <div className="action-buttons">
              <button
                type="button"
                className="secondary-button"
                onClick={handleOpenCamera}
              >
                Take photo with camera
              </button>
              <button
                type="button"
                className="primary-button"
                onClick={handleProcessQueuedFiles}
                disabled={!pendingFiles.length || isUploading}
              >
                {isUploading ? 'Processing...' : 'Start processing'}
              </button>
            </div>

            {pendingFiles.length > 0 ? (
              <div className="queued-files">
                <p className="queued-title">Ready to process ({pendingFiles.length})</p>
                <div className="queued-grid">
                  {pendingFiles.map((file) => (
                    <div className="queued-file" key={`${file.name}-${file.lastModified}`}>
                      <div>
                        <p className="file-name">{file.name}</p>
                        <p className="queued-meta">{(file.size / 1024 / 1024).toFixed(1)} MB</p>
                      </div>
                      <span className="queued-pill">
                        {file.type?.includes('/') ? file.type.split('/')[1] : file.type || 'file'}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <p className="upload-hint inline">Add photos or capture a new one, then start processing.</p>
            )}
          </div>

          {isUploading && (
            <div className="status-message">Processing files...</div>
          )}

          {errorMessage && (
            <div className="error-message">{errorMessage}</div>
          )}

          {processedImages.length > 0 && !showResults && (
            <button type="button" className="secondary-button view-report" onClick={() => setShowResults(true)}>
              View latest report
            </button>
          )}
        </div>
      </div>

      <div className={`results-page ${showResults ? 'visible' : ''}`}>
        <div className="results-content">
          <div className="results-header">
            <div>
              <p className="eyebrow">Step 2</p>
              <h2>Visual report</h2>
              <p className="subtitle">Annotated results and live cost projections.</p>
            </div>
            <button type="button" className="secondary-button" onClick={handleViewUpload}>
              Upload more files
            </button>
          </div>

          <div className="results-grid">
            {processedImages.map((item) => (
              <div className="result-card" key={item.id}>
                <div className="result-card__image">
                  {item.imageSrc ? (
                    <img
                      src={item.imageSrc}
                      alt={`Processed ${item.fileName}`}
                      className="processed-image"
                    />
                  ) : (
                    <p className="no-preview">No preview available</p>
                  )}
                </div>
                <div className="result-actions">
                  <button type="button" className="primary-button" onClick={() => handleOpenDetail(item.id)}>
                    View cost insights
                  </button>
                </div>
              </div>
            ))}
          </div>

          {aggregateReport && (
            <div className="aggregate-report">
              <h3>Total portfolio outlook</h3>
              <div className="overview-grid">
                {aggregateReport.totals.map((total) => (
                  <motion.div 
                    className="metric-card horizon-card" 
                    key={`total-${total.year}`}
                    whileHover={{ 
                      scale: 1.05, 
                      boxShadow: "0 20px 40px rgba(15, 23, 42, 0.15)",
                      transition: { duration: 0.3 }
                    }}
                    whileTap={{ scale: 0.98 }}
                    onClick={() => setSelectedHorizonYear(total.year)}
                    style={{ cursor: 'pointer' }}
                  >
                    <p className="metric-label">{total.year}-year horizon</p>
                    <p className="metric-value">{formatCurrency(total.total)}</p>
                    <p className="metric-subtext">Across all uploaded photos</p>
                    <motion.div 
                      className="horizon-card-overlay"
                      initial={{ opacity: 0 }}
                      whileHover={{ opacity: 1 }}
                    >
                      <span>Click to view details</span>
                    </motion.div>
                  </motion.div>
                ))}
              </div>

              {aggregateReport.topSystems.length > 0 && (
                <div className="top-systems">
                  <p className="metric-label">Top cost drivers (15-year)</p>
                  <div className="top-systems__list">
                    {aggregateReport.topSystems.map((system) => (
                      <motion.div 
                        className="top-system clickable" 
                        key={system.label}
                        whileHover={{ 
                          x: 8,
                          backgroundColor: 'rgba(99, 102, 241, 0.05)',
                          transition: { duration: 0.2 }
                        }}
                        whileTap={{ scale: 0.98 }}
                        onClick={() => setSelectedSystemName(system.label)}
                      >
                        <span>{system.label}</span>
                        <strong>{formatCurrency(system.value)}</strong>
                      </motion.div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {(isValuationLoading || valuationReport || valuationError) && (
            <div className="valuation-report">
              <h3>Property valuation & cost outlook</h3>
              {isValuationLoading && <p className="status-message inline">Calculating valuation...</p>}
              {valuationError && <p className="error-message inline">{valuationError}</p>}

              {valuationReport && (
                <div className="valuation-grid">
                  <div className="valuation-card">
                    <p className="metric-label">Address</p>
                    <p className="valuation-value">{valuationReport.address}</p>
                    <p className="metric-label">Purchase price</p>
                    <p className="valuation-value">{formatCurrency(valuationReport.current_price)}</p>
                  </div>
                  <div className="valuation-card">
                    <p className="metric-label">10-year property value</p>
                    <p className="valuation-value">
                      {formatCurrency(
                        valuationReport.valuation?.valuation?.['10_year_summary']?.final_property_value || 0
                      )}
                    </p>
                    <p className="metric-label">Projected ROI</p>
                    <p className="valuation-subtext">
                      {valuationReport.valuation?.valuation?.['10_year_summary']?.total_roi_percentage || 0}%
                    </p>
                  </div>
                  <div className="valuation-card">
                    <p className="metric-label">10-year repair budget</p>
                    <p className="valuation-value">{formatCurrency(tenYearRepairBudget)}</p>
                    <p className="metric-label">Net projected value</p>
                    <p className="valuation-subtext">
                      {formatCurrency(
                        (valuationReport.valuation?.valuation?.['10_year_summary']?.final_property_value || 0) -
                          tenYearRepairBudget
                      )}
                    </p>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {selectedImage && (
        <div className={`detail-overlay ${selectedImage ? 'visible' : ''}`}>
          <div className="detail-canvas">
            {selectedImage.imageSrc && (
              <div className="detail-hero">
                <img src={selectedImage.imageSrc} alt={selectedImage.fileName} />
              </div>
            )}
            <div className="detail-body">
              <div className="detail-body__header">
                <div>
                  <p className="eyebrow">Cost insights</p>
                  <h3>{selectedImage.fileName}</h3>
                  <p className="subtitle">
                    {selectedImage.costProfiles?.length || 0} system(s) analyzed · {selectedImage.detectedCategory || 'Mixed areas'}
                  </p>
                </div>
                <button type="button" className="close-detail" onClick={handleCloseDetail}>
                  Close
                </button>
              </div>

              <div className="detail-body__content">
                {plotlyFigure && (
                  <div className="graph-card">
                    <div className="graph-card__header">
                      <div>
                        <p className="meta-label">Cumulative spend (15 years)</p>
                        <h4>
                          {formatCurrency(
                            selectedImage.costProfiles.reduce((sum, profile) => {
                              const horizon = profile.horizons.find((h) => h.year === 15)?.total || 0;
                              return sum + horizon;
                            }, 0)
                          )}
                        </h4>
                        <p className="meta-hint">Interactive Plotly chart</p>
                      </div>
                    </div>
                    <div className="plotly-wrapper">
                      <Plot
                        data={plotlyFigure.data}
                        layout={plotlyFigure.layout}
                        config={plotlyFigure.config}
                        className="plotly-graph"
                      />
                    </div>
                  </div>
                )}
                {selectedImage.costProfiles?.length ? (
                  selectedImage.costProfiles.map((profile) => {
                    const fiveYear = profile.horizons.find((h) => h.year === 5)?.total || 0;
                    const tenYear = profile.horizons.find((h) => h.year === 10)?.total || 0;
                    const fifteenYear = profile.horizons.find((h) => h.year === 15)?.total || 0;
                    const scheduledEvents = profile.yearlySeries.filter((entry) => entry.cost > 0);

                    return (
                      <div className="detail-card" key={`${selectedImage.id}-${profile.label}`}>
                        <div className="analysis-card__header">
                          <div>
                            <p className="analysis-title">{profile.label}</p>
                            <p className="analysis-subtitle">{profile.category}</p>
                          </div>
                          <span className={`severity-pill severity-${profile.severity}`}>
                            Severity {profile.severity}/5
                          </span>
                        </div>

                        <div className="profile-overview">
                          <div>
                            <p className="meta-label">5-year cost</p>
                            <p className="meta-value">{formatCurrency(fiveYear)}</p>
                            <p className="meta-hint">Immediate remediation budget</p>
                          </div>
                          <div>
                            <p className="meta-label">10-year cost</p>
                            <p className="meta-value">{formatCurrency(tenYear)}</p>
                            <p className="meta-hint">Medium-term upkeep</p>
                          </div>
                          <div>
                            <p className="meta-label">15-year cost</p>
                            <p className="meta-value">{formatCurrency(fifteenYear)}</p>
                            <p className="meta-hint">Full lifecycle outlook</p>
                          </div>
                        </div>

                        <div className="horizon-bars">
                          {profile.horizons.map((horizon) => (
                            <div className="horizon-bar" key={`${profile.label}-${horizon.year}`}>
                              <div className="horizon-bar__label">{horizon.year}-year</div>
                              <div className="horizon-bar__track">
                                <div
                                  className="horizon-bar__fill"
                                  style={{
                                    width: `${Math.min(
                                      100,
                                      Math.max(0, (horizon.total / profile.maxHorizon) * 100)
                                    )}%`,
                                  }}
                                />
                              </div>
                              <div className="horizon-bar__value">{formatCurrency(horizon.total)}</div>
                            </div>
                          ))}
                        </div>

                        <div className="analysis-meta">
                          <div>
                            <p className="meta-label">Highest year</p>
                            <p className="meta-value">
                              {formatCurrency(
                                Math.max(...profile.yearlySeries.map((entry) => entry.cost), 0)
                              )}
                            </p>
                          </div>
                          <div>
                            <p className="meta-label">Active years</p>
                            <p className="meta-value">
                              {profile.yearlySeries.filter((entry) => entry.cost > 0).length}
                            </p>
                          </div>
                        </div>

                      <div className="yearly-chart">
                        {profile.yearlySeries.map((entry) => (
                          <div className="year-bar" key={`${profile.label}-${entry.year}`}>
                            <div
                              className="year-bar__fill"
                              style={{
                                height: `${Math.min(
                                  100,
                                  Math.max(0, (entry.cost / profile.maxYearly) * 100)
                                )}%`,
                              }}
                              title={`Year ${entry.year}: ${formatCurrency(entry.cost)}`}
                            />
                          </div>
                        ))}
                      </div>

                        <div className="event-breakdown">
                          <p className="event-breakdown__title">Scheduled work</p>
                          {scheduledEvents.length ? (
                            scheduledEvents.map((event) => (
                              <div className="event-row" key={`${profile.label}-${event.year}`}>
                                <div>
                                  <p className="event-year">Year {event.year}</p>
                                  <p className="event-note">{event.scheduled_work}</p>
                                </div>
                                <span className="event-cost">{formatCurrency(event.cost)}</span>
                              </div>
                            ))
                          ) : (
                            <p className="event-empty">No maintenance events are forecast within 15 years.</p>
                          )}
                        </div>

                        <p className="projection-summary">{profile.summary}</p>
                      </div>
                    );
                  })
                ) : (
                  <div className="pricing-placeholder">Pricing data unavailable for this photo.</div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {showCameraModal && (
        <div className="detail-overlay visible">
          <div className="camera-modal">
            <div className="camera-modal__header">
              <h3>Take a photo</h3>
              <button type="button" className="close-detail" onClick={handleCloseCamera}>
                Close
              </button>
            </div>
            <div className="camera-preview">
              <video ref={videoRef} autoPlay playsInline muted className="camera-video" />
              <canvas ref={canvasRef} style={{ display: 'none' }} />
            </div>
            <div className="camera-actions">
              <button type="button" className="primary-button" onClick={handleCapturePhoto}>
                Capture Photo
              </button>
            </div>
          </div>
        </div>
      )}

      <AnimatePresence>
        {horizonModalData && (
          <motion.div 
            className="horizon-modal-overlay"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={() => setSelectedHorizonYear(null)}
          >
            <motion.div 
              className="horizon-modal"
              initial={{ scale: 0.9, y: 50 }}
              animate={{ scale: 1, y: 0 }}
              exit={{ scale: 0.9, y: 50 }}
              transition={{ type: "spring", damping: 25, stiffness: 300 }}
              onClick={(e) => e.stopPropagation()}
            >
              <div className="horizon-modal__header">
                <div>
                  <h2>{horizonModalData.year}-Year Cost Horizon</h2>
                  <p className="horizon-modal__subtitle">
                    Total projected costs: <strong>{formatCurrency(horizonModalData.total)}</strong>
                  </p>
                </div>
                <button 
                  type="button" 
                  className="close-detail" 
                  onClick={() => setSelectedHorizonYear(null)}
                >
                  Close
                </button>
              </div>

              <div className="horizon-modal__content">
                {/* Cumulative Area Chart */}
                <motion.div 
                  className="chart-section"
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.1 }}
                >
                  <h3>Cumulative Cost Growth</h3>
                  <ResponsiveContainer width="100%" height={300}>
                    <AreaChart 
                      data={horizonModalData.yearlyBreakdown.map((item, idx) => ({
                        year: item.year,
                        cumulative: horizonModalData.yearlyBreakdown
                          .slice(0, idx + 1)
                          .reduce((sum, y) => sum + y.totalCost, 0)
                      }))}
                      margin={{ top: 10, right: 30, left: 0, bottom: 0 }}
                    >
                      <defs>
                        <linearGradient id="colorCumulative" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor="#10b981" stopOpacity={0.8}/>
                          <stop offset="95%" stopColor="#10b981" stopOpacity={0.1}/>
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                      <XAxis 
                        dataKey="year" 
                        stroke="#6b7280"
                        label={{ value: 'Year', position: 'insideBottom', offset: -5 }}
                      />
                      <YAxis 
                        stroke="#6b7280"
                        tickFormatter={(value) => `€${(value / 1000).toFixed(0)}k`}
                      />
                      <Tooltip 
                        formatter={(value) => formatCurrency(value)}
                        contentStyle={{ 
                          backgroundColor: 'rgba(255, 255, 255, 0.95)', 
                          border: '1px solid #e5e7eb',
                          borderRadius: '8px',
                          boxShadow: '0 4px 12px rgba(0,0,0,0.1)'
                        }}
                      />
                      <Area 
                        type="monotone" 
                        dataKey="cumulative" 
                        stroke="#10b981" 
                        strokeWidth={3}
                        fillOpacity={1} 
                        fill="url(#colorCumulative)" 
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                </motion.div>

                {/* Annual Cost Breakdown Bar Chart */}
                <motion.div 
                  className="chart-section"
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.2 }}
                >
                  <h3>Annual Cost Breakdown</h3>
                  <ResponsiveContainer width="100%" height={300}>
                    <BarChart 
                      data={horizonModalData.yearlyBreakdown}
                      margin={{ top: 10, right: 30, left: 0, bottom: 0 }}
                    >
                      <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                      <XAxis 
                        dataKey="year" 
                        stroke="#6b7280"
                        label={{ value: 'Year', position: 'insideBottom', offset: -5 }}
                      />
                      <YAxis 
                        stroke="#6b7280"
                        tickFormatter={(value) => `€${(value / 1000).toFixed(0)}k`}
                      />
                      <Tooltip 
                        formatter={(value) => formatCurrency(value)}
                        contentStyle={{ 
                          backgroundColor: 'rgba(255, 255, 255, 0.95)', 
                          border: '1px solid #e5e7eb',
                          borderRadius: '8px',
                          boxShadow: '0 4px 12px rgba(0,0,0,0.1)'
                        }}
                      />
                      <Bar 
                        dataKey="totalCost" 
                        fill="#f97316" 
                        radius={[8, 8, 0, 0]}
                        animationDuration={800}
                      />
                    </BarChart>
                  </ResponsiveContainer>
                </motion.div>

                {/* System Breakdown Pie Chart */}
                {horizonModalData.systemBreakdown.length > 0 && (
                  <motion.div 
                    className="chart-section"
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: 0.3 }}
                  >
                    <h3>Cost Distribution by System</h3>
                    <ResponsiveContainer width="100%" height={350}>
                      <PieChart>
                        <Pie
                          data={horizonModalData.systemBreakdown}
                          cx="50%"
                          cy="50%"
                          labelLine={false}
                          label={({ name, percent }) => `${name}: ${(percent * 100).toFixed(0)}%`}
                          outerRadius={120}
                          fill="#8884d8"
                          dataKey="value"
                          animationDuration={800}
                        >
                          {horizonModalData.systemBreakdown.map((entry, index) => (
                            <Cell 
                              key={`cell-${index}`} 
                              fill={[
                                '#10b981', '#f97316', '#059669', '#ea580c', 
                                '#14b8a6', '#fb923c', '#0d9488', '#fdba74'
                              ][index % 8]} 
                            />
                          ))}
                        </Pie>
                        <Tooltip 
                          formatter={(value) => formatCurrency(value)}
                          contentStyle={{ 
                            backgroundColor: 'rgba(255, 255, 255, 0.95)', 
                            border: '1px solid #e5e7eb',
                            borderRadius: '8px',
                            boxShadow: '0 4px 12px rgba(0,0,0,0.1)'
                          }}
                        />
                        <Legend 
                          verticalAlign="bottom" 
                          height={36}
                          formatter={(value, entry) => `${value}: ${formatCurrency(entry.payload.value)}`}
                        />
                      </PieChart>
                    </ResponsiveContainer>
                  </motion.div>
                )}

                {/* System-wise breakdown list */}
                <motion.div 
                  className="system-breakdown-list"
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.5 }}
                >
                  <h3>Detailed System Costs</h3>
                  <div className="system-breakdown-grid">
                    {horizonModalData.systemBreakdown.map((system, idx) => (
                      <motion.div 
                        key={system.name}
                        className="system-breakdown-item"
                        initial={{ opacity: 0, x: -20 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ delay: 0.5 + idx * 0.05 }}
                      >
                        <div className="system-breakdown-header">
                          <span className="system-breakdown-name">{system.name}</span>
                          <span className="system-breakdown-value">{formatCurrency(system.value)}</span>
                        </div>
                        <div className="system-breakdown-bar">
                          <motion.div 
                            className="system-breakdown-fill"
                            initial={{ width: 0 }}
                            animate={{ width: `${(system.value / horizonModalData.total) * 100}%` }}
                            transition={{ duration: 0.8, delay: 0.5 + idx * 0.05 }}
                            style={{
                              background: [
                                '#10b981', '#f97316', '#059669', '#ea580c', 
                                '#14b8a6', '#fb923c', '#0d9488', '#fdba74'
                              ][idx % 8]
                            }}
                          />
                        </div>
                        <span className="system-breakdown-percent">
                          {((system.value / horizonModalData.total) * 100).toFixed(1)}% of total
                        </span>
                      </motion.div>
                    ))}
                  </div>
                </motion.div>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {systemModalData && (
          <motion.div 
            className="horizon-modal-overlay"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={() => setSelectedSystemName(null)}
          >
            <motion.div 
              className="horizon-modal"
              initial={{ scale: 0.9, y: 50 }}
              animate={{ scale: 1, y: 0 }}
              exit={{ scale: 0.9, y: 50 }}
              transition={{ type: "spring", damping: 25, stiffness: 300 }}
              onClick={(e) => e.stopPropagation()}
            >
              <div className="horizon-modal__header">
                <div>
                  <h2>{systemModalData.systemName}</h2>
                  <p className="horizon-modal__subtitle">
                    {systemModalData.category} • Total 15-year cost: <strong>{formatCurrency(systemModalData.totalCost)}</strong>
                  </p>
                  <div style={{ display: 'flex', gap: '12px', marginTop: '8px' }}>
                    <span className={`severity-pill severity-${systemModalData.averageSeverity}`}>
                      Avg Severity {systemModalData.averageSeverity}/5
                    </span>
                    <span className="info-pill">
                      {systemModalData.instanceCount} instance{systemModalData.instanceCount > 1 ? 's' : ''} detected
                    </span>
                  </div>
                </div>
                <button 
                  type="button" 
                  className="close-detail" 
                  onClick={() => setSelectedSystemName(null)}
                >
                  Close
                </button>
              </div>

              <div className="horizon-modal__content">
                {/* Cumulative Cost by Year */}
                <motion.div 
                  className="chart-section"
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.1 }}
                >
                  <h3>Cumulative Cost Projection</h3>
                  <ResponsiveContainer width="100%" height={320}>
                    <AreaChart 
                      data={systemModalData.yearlyData.map((item, idx) => ({
                        year: item.year,
                        cumulative: systemModalData.yearlyData
                          .slice(0, idx + 1)
                          .reduce((sum, y) => sum + y.totalCost, 0)
                      }))}
                      margin={{ top: 10, right: 30, left: 0, bottom: 0 }}
                    >
                      <defs>
                        <linearGradient id="colorSystemCumulative" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor="#10b981" stopOpacity={0.8}/>
                          <stop offset="95%" stopColor="#10b981" stopOpacity={0.1}/>
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                      <XAxis 
                        dataKey="year" 
                        stroke="#6b7280"
                        label={{ value: 'Year', position: 'insideBottom', offset: -5 }}
                      />
                      <YAxis 
                        stroke="#6b7280"
                        tickFormatter={(value) => `€${(value / 1000).toFixed(0)}k`}
                      />
                      <Tooltip 
                        formatter={(value) => formatCurrency(value)}
                        contentStyle={{ 
                          backgroundColor: 'rgba(255, 255, 255, 0.95)', 
                          border: '1px solid #e5e7eb',
                          borderRadius: '8px',
                          boxShadow: '0 4px 12px rgba(0,0,0,0.1)'
                        }}
                      />
                      <Area 
                        type="monotone" 
                        dataKey="cumulative" 
                        stroke="#10b981" 
                        strokeWidth={3}
                        fillOpacity={1} 
                        fill="url(#colorSystemCumulative)" 
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                </motion.div>

                {/* Annual Costs with Stacked Instances */}
                <motion.div 
                  className="chart-section"
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.2 }}
                >
                  <h3>Annual Cost Breakdown</h3>
                  <ResponsiveContainer width="100%" height={320}>
                    <BarChart 
                      data={systemModalData.yearlyData.filter(d => d.totalCost > 0)}
                      margin={{ top: 10, right: 30, left: 0, bottom: 0 }}
                    >
                      <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                      <XAxis 
                        dataKey="year" 
                        stroke="#6b7280"
                        label={{ value: 'Year', position: 'insideBottom', offset: -5 }}
                      />
                      <YAxis 
                        stroke="#6b7280"
                        tickFormatter={(value) => `€${(value / 1000).toFixed(0)}k`}
                      />
                      <Tooltip 
                        formatter={(value) => formatCurrency(value)}
                        contentStyle={{ 
                          backgroundColor: 'rgba(255, 255, 255, 0.95)', 
                          border: '1px solid #e5e7eb',
                          borderRadius: '8px',
                          boxShadow: '0 4px 12px rgba(0,0,0,0.1)'
                        }}
                        content={({ active, payload }) => {
                          if (!active || !payload?.[0]) return null;
                          const data = payload[0].payload;
                          return (
                            <div style={{ 
                              backgroundColor: 'rgba(255, 255, 255, 0.95)', 
                              border: '1px solid #e5e7eb',
                              borderRadius: '8px',
                              padding: '12px',
                              boxShadow: '0 4px 12px rgba(0,0,0,0.1)'
                            }}>
                              <p style={{ margin: '0 0 8px', fontWeight: 'bold' }}>Year {data.year}</p>
                              <p style={{ margin: '0 0 8px', color: '#6b7280' }}>
                                Total: {formatCurrency(data.totalCost)}
                              </p>
                              {data.instances.length > 0 && (
                                <div style={{ borderTop: '1px solid #e5e7eb', paddingTop: '8px', marginTop: '8px' }}>
                                  {data.instances.map((inst, idx) => (
                                    <div key={idx} style={{ fontSize: '12px', margin: '4px 0' }}>
                                      <strong>{inst.imageName}:</strong> {formatCurrency(inst.cost)}
                                      <div style={{ color: '#6b7280', fontSize: '11px' }}>{inst.work}</div>
                                    </div>
                                  ))}
                                </div>
                              )}
                            </div>
                          );
                        }}
                      />
                      <Bar 
                        dataKey="totalCost" 
                        fill="#f97316" 
                        radius={[8, 8, 0, 0]}
                        animationDuration={800}
                      />
                    </BarChart>
                  </ResponsiveContainer>
                </motion.div>

                {/* Year-over-year comparison line chart */}
                <motion.div 
                  className="chart-section"
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.4 }}
                >
                  <h3>Cost Trend Analysis</h3>
                  <ResponsiveContainer width="100%" height={300}>
                    <LineChart 
                      data={systemModalData.yearlyData}
                      margin={{ top: 10, right: 30, left: 0, bottom: 0 }}
                    >
                      <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                      <XAxis 
                        dataKey="year" 
                        stroke="#6b7280"
                        label={{ value: 'Year', position: 'insideBottom', offset: -5 }}
                      />
                      <YAxis 
                        stroke="#6b7280"
                        tickFormatter={(value) => `€${(value / 1000).toFixed(0)}k`}
                      />
                      <Tooltip 
                        formatter={(value) => formatCurrency(value)}
                        contentStyle={{ 
                          backgroundColor: 'rgba(255, 255, 255, 0.95)', 
                          border: '1px solid #e5e7eb',
                          borderRadius: '8px',
                          boxShadow: '0 4px 12px rgba(0,0,0,0.1)'
                        }}
                      />
                      <Legend />
                      <Line 
                        type="monotone" 
                        dataKey="totalCost" 
                        stroke="#f97316" 
                        strokeWidth={3}
                        name="Annual Cost"
                        dot={{ fill: '#f97316', r: 6 }}
                        activeDot={{ r: 8 }}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </motion.div>

                
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export default App;
