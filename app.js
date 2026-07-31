class NextTrainApp {
    constructor() {
        this.data = null;
        this.userLocation = null;
        this.nearestStation = null;
        this.selectedLine = null;
        this.selectedDirection = null;
        this.countdownInterval = null;
        this.currentTrainIndex = 0;

        this.loadingEl = document.getElementById('loading');
        this.errorEl = document.getElementById('error');
        this.appEl = document.getElementById('app');
        this.stationNameEl = document.getElementById('stationName');
        this.distanceEl = document.getElementById('distance');
        this.lineSelectorEl = document.getElementById('lineSelector');
        this.directionSelectorEl = document.getElementById('directionSelector');
        this.trainTimeEl = document.getElementById('trainTime');
        this.trainTagEl = document.getElementById('trainTag');
        this.countdownEl = document.getElementById('countdown');
        this.sortByDistanceBtnEl = document.getElementById('sortByDistanceBtn');
        this.inputStationBtnEl = document.getElementById('inputStationBtn');
        this.languageSelectorEl = document.getElementById('languageSelector');
        this.currentLanguageEl = document.getElementById('currentLanguage');

        this.setupLanguageSelector();
        this.init();
    }

    formatLineName(route) {
        if (/^\d+$/.test(route)) {
            // Numeric route (e.g., "1" -> "1号线" or "Line 1")
            return window.i18n.t('lineNameNumeric', { number: route });
        } else {
            // Non-numeric route (e.g., "昌平线" -> "昌平线" or "Changping Line")
            return window.i18n.t('lineNameNonNumeric', { name: route });
        }
    }

    mergeData(routesData, schedules) {
        // Get all unique stations from schedules
        const allStationNames = new Set();
        schedules.forEach(schedule => allStationNames.add(schedule.station));

        const stationsWithSchedules = Array.from(allStationNames).map(stationName => {
            // Get coordinates from routes.json if available
            const coordinates = routesData.coordinates[stationName];
            const lat = coordinates ? coordinates[0] : 39.9042; // Default Beijing center
            const lng = coordinates ? coordinates[1] : 116.4074;

            // Get schedules for this station
            const stationSchedules = schedules.filter(schedule =>
                schedule.station === stationName
            );

            // Group by route/line
            const uniqueRoutes = [...new Set(stationSchedules.map(s => s.route))];
            const lines = uniqueRoutes.map(route => {
                const lineName = this.formatLineName(route);
                // Find the line by matching the route number with the lineName in routes.json
                const line = routesData.lines.find(l => l.lineName === route);
                const lineSchedules = stationSchedules.filter(schedule =>
                    schedule.route === route
                );

                const directions = this.groupSchedulesByDirection(lineSchedules);

                return {
                    lineName,
                    route, // Store original route for formatting
                    lineColor: line ? line.lineColor : '#999999', // Default color for unknown lines
                    directions
                };
            });

            return {
                name: stationName,
                lat,
                lng,
                lines
            };
        });

        return { stations: stationsWithSchedules };
    }

    getApplicableDays(operatingTime) {
        switch (operatingTime) {
            case '工作日':
                return [1, 2, 3, 4, 5]; // Monday to Friday
            case '双休日':
                return [0, 6]; // Sunday and Saturday
            case '星期五':
                return [5]; // Friday only
            case '平日':
                return [0, 1, 2, 3, 4, 6]; // Everyday except Friday
            default:
                return [0, 1, 2, 3, 4, 5, 6]; // Default to everyday
        }
    }

    groupSchedulesByDirection(schedules) {
        const directions = new Map();

        schedules.forEach(schedule => {
            const direction = schedule.destination;
            if (!directions.has(direction)) {
                directions.set(direction, {
                    direction,
                    schedules: []
                });
            }

            const directionData = directions.get(direction);
            directionData.schedules.push({
                operatingTime: schedule.operating_time,
                times: schedule.schedule_times,
                applicableDays: this.getApplicableDays(schedule.operating_time)
            });
        });

        return Array.from(directions.values());
    }

    getBeijingTime() {
        const now = new Date();
        const beijingTime = new Date(now.getTime() + (now.getTimezoneOffset() * 60000) + (8 * 3600000));
        return beijingTime;
    }

    getCurrentScheduleTimes() {
        const beijingTime = this.getBeijingTime();
        const currentDayOfWeek = beijingTime.getDay(); // 0=Sunday, 1=Monday, ..., 6=Saturday

        // Find all schedules that apply to the current day
        const applicableSchedules = this.selectedDirection.schedules.filter(schedule =>
            schedule.applicableDays.includes(currentDayOfWeek)
        );

        if (applicableSchedules.length === 0) {
            // No applicable schedules found, fallback to workday schedule
            const workdaySchedule = this.selectedDirection.schedules.find(schedule =>
                schedule.operatingTime === '工作日'
            );
            return workdaySchedule ? workdaySchedule.times : [];
        }

        // If multiple schedules apply, prioritize by specificity:
        // Schedules with fewer applicable days are more specific and have higher priority
        applicableSchedules.sort((a, b) => a.applicableDays.length - b.applicableDays.length);

        return applicableSchedules[0].times;
    }

    setupLanguageSelector() {
        // Set up language selector - direct toggle between zh and en
        this.languageSelectorEl.addEventListener('click', () => {
            const currentLang = window.i18n.getCurrentLanguage();
            const newLang = currentLang === 'zh' ? 'en' : 'zh';
            window.i18n.setLanguage(newLang);
        });

        // Listen for language changes
        window.addEventListener('languageChanged', () => {
            this.updateLanguageDisplay();
            this.translateUI();
        });

        // Initial language setup
        this.updateLanguageDisplay();
        this.translateUI();
    }

    updateLanguageDisplay() {
        const currentLang = window.i18n.getCurrentLanguage();
        const langMap = {
            'zh': '中文',
            'en': 'EN'
        };
        this.currentLanguageEl.textContent = langMap[currentLang];
    }

    translateUI() {
        // Translate elements with data-i18n attribute
        document.querySelectorAll('[data-i18n]').forEach(el => {
            const key = el.getAttribute('data-i18n');
            el.textContent = window.i18n.t(key);
        });

        // Translate title attributes
        document.querySelectorAll('[data-i18n-title]').forEach(el => {
            const key = el.getAttribute('data-i18n-title');
            el.setAttribute('title', window.i18n.t(key));
        });

        // Update dynamic content if app is running
        if (this.nearestStation) {
            this.updateStationDisplay();
            this.renderLineSelector();
            this.renderDirectionSelector();
            this.updateTrainInfo();
        }
    }

    async init() {
        try {
            await this.loadData();
            try {
                await this.getUserLocation();
            } catch (locationError) {
                this.showLocationFallback();
                return;
            }
            this.findNearestStation();
            this.setupUI();
            this.startCountdown();
        } catch (error) {
            this.showError(error.message);
        }
    }

    async loadData() {
        try {
            const [routesResponse, schedulesResponse] = await Promise.all([
                fetch('data/routes.json'),
                fetch('data/timetable.jsonl')
            ]);

            if (!routesResponse.ok || !schedulesResponse.ok) {
                throw new Error(window.i18n.t('cannotLoadData'));
            }

            const routesData = await routesResponse.json();
            const schedulesText = await schedulesResponse.text();

            // Parse JSONL format
            const schedules = schedulesText.trim().split('\n')
                .filter(line => line.trim())
                .map(line => JSON.parse(line));

            this.data = this.mergeData(routesData, schedules);
        } catch (error) {
            throw new Error(window.i18n.t('dataLoadFailed'));
        }
    }

    async getUserLocation() {
        return new Promise((resolve, reject) => {
            if (!navigator.geolocation) {
                reject(new Error(window.i18n.t('locationNotSupported')));
                return;
            }

            navigator.geolocation.getCurrentPosition(
                (position) => {
                    this.userLocation = {
                        lat: position.coords.latitude,
                        lng: position.coords.longitude
                    };
                    resolve();
                },
                (error) => {
                    let message = window.i18n.t('locationFailed');
                    switch (error.code) {
                        case error.PERMISSION_DENIED:
                            message = window.i18n.t('locationPermissionDenied');
                            break;
                        case error.POSITION_UNAVAILABLE:
                            message = window.i18n.t('locationUnavailable');
                            break;
                        case error.TIMEOUT:
                            message = window.i18n.t('locationTimeout');
                            break;
                    }
                    reject(new Error(message));
                },
                {
                    enableHighAccuracy: true,
                    timeout: 10000,
                    maximumAge: 300000
                }
            );
        });
    }

    calculateDistance(lat1, lng1, lat2, lng2) {
        const R = 6371;
        const dLat = this.toRad(lat2 - lat1);
        const dLng = this.toRad(lng2 - lng1);
        const a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
            Math.cos(this.toRad(lat1)) * Math.cos(this.toRad(lat2)) *
            Math.sin(dLng / 2) * Math.sin(dLng / 2);
        const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
        return R * c;
    }

    toRad(value) {
        return value * Math.PI / 180;
    }

    findNearestStation() {
        let minDistance = Infinity;
        let nearest = null;

        this.data.stations.forEach(station => {
            const distance = this.calculateDistance(
                this.userLocation.lat,
                this.userLocation.lng,
                station.lat,
                station.lng
            );

            if (distance < minDistance) {
                minDistance = distance;
                nearest = { ...station, distance };
            }
        });

        this.nearestStation = nearest;
        this.selectedLine = nearest.lines[0];
        this.selectedDirection = nearest.lines[0].directions[0];
        this.currentTrainIndex = this.getNextTrainIndex();
    }

    setupUI() {
        this.loadingEl.style.display = 'none';
        this.errorEl.style.display = 'none';
        this.appEl.style.display = 'block';

        this.updateStationDisplay();
        this.renderLineSelector();
        this.renderDirectionSelector();
        this.updateTrainInfo();

        // 设置按钮事件监听器
        this.sortByDistanceBtnEl.onclick = () => this.showStationSelector();
        this.inputStationBtnEl.onclick = () => this.makeStationNameEditable();

        // 设置倒计时框点击事件
        this.setupClickGestures();
    }

    setupClickGestures() {
        const leftArrow = document.querySelector('.click-indicator.left');
        const rightArrow = document.querySelector('.click-indicator.right');

        leftArrow.addEventListener('click', (e) => {
            e.stopPropagation();
            this.showPreviousTrain();
        });

        rightArrow.addEventListener('click', (e) => {
            e.stopPropagation();
            this.showNextTrain();
        });
    }

    updateStationDisplay() {
        this.stationNameEl.textContent = this.nearestStation.name;
        this.distanceEl.textContent = this.nearestStation.distance > 0
            ? window.i18n.t('distanceAway', { distance: (this.nearestStation.distance * 1000).toFixed(0) })
            : window.i18n.t('selectedStation');
    }

    renderLineSelector() {
        this.lineSelectorEl.innerHTML = '';

        // 当前线路颜色作为全局主题色，驱动方向选择框、进度条等元素
        document.documentElement.style.setProperty(
            '--line-color', this.selectedLine.lineColor || '#8A8D93'
        );

        this.nearestStation.lines.forEach(line => {
            const btn = document.createElement('button');
            btn.className = `line-btn ${line.lineName === this.selectedLine.lineName ? 'active' : ''}`;
            btn.style.setProperty('--line-color', line.lineColor || '#8A8D93');

            // Use formatLineName to get the localized line name for display
            btn.textContent = this.formatLineName(line.route);
            btn.onclick = () => this.selectLine(line);
            this.lineSelectorEl.appendChild(btn);
        });
    }

    renderDirectionSelector() {
        this.directionSelectorEl.innerHTML = '';

        this.selectedLine.directions.forEach(direction => {
            const btn = document.createElement('button');
            btn.className = `direction-btn ${direction.direction === this.selectedDirection.direction ? 'active' : ''}`;
            btn.textContent = window.i18n.t('nextTrainTo', { destination: direction.direction });
            btn.onclick = () => this.selectDirection(direction);
            this.directionSelectorEl.appendChild(btn);
        });
    }

    selectLine(line) {
        this.selectedLine = line;
        this.selectedDirection = line.directions[0];
        this.currentTrainIndex = this.getNextTrainIndex(); // Set to next train when changing line
        this.renderLineSelector();
        this.renderDirectionSelector();
        this.updateTrainInfo();
    }

    selectDirection(direction) {
        this.selectedDirection = direction;
        this.currentTrainIndex = this.getNextTrainIndex(); // Set to next train when changing direction
        this.renderDirectionSelector();
        this.updateTrainInfo();
    }

    showPreviousTrain() {
        const allTrains = this.getAllTrains();
        if (allTrains.length === 0) return;

        if (this.currentTrainIndex > 0) {
            this.currentTrainIndex--;
        } else {
            // Cycle to last train
            this.currentTrainIndex = allTrains.length - 1;
        }
        this.updateTrainInfo();
    }

    showNextTrain() {
        const allTrains = this.getAllTrains();
        if (allTrains.length === 0) return;

        if (this.currentTrainIndex < allTrains.length - 1) {
            this.currentTrainIndex++;
        } else {
            // Cycle to first train
            this.currentTrainIndex = 0;
        }
        this.updateTrainInfo();
    }

    updateTrainInfo() {
        const beijingTime = this.getBeijingTime();
        const currentTime = beijingTime.getHours() * 60 + beijingTime.getMinutes();
        const allTrains = this.getAllTrains();
        const currentTrain = allTrains[this.currentTrainIndex];

        if (!currentTrain) {
            this.trainTimeEl.textContent = window.i18n.t('trainTimeDefault');
            this.trainTagEl.style.display = 'none';
            this.countdownEl.textContent = window.i18n.t('noService');
            return;
        }

        // Display time
        this.trainTimeEl.textContent = currentTrain.time;

        // Display special tags for first and last trains
        if (this.currentTrainIndex === 0) {
            this.trainTagEl.textContent = window.i18n.t('firstTrain');
            this.trainTagEl.style.display = 'block';
        } else if (this.currentTrainIndex === allTrains.length - 1) {
            this.trainTagEl.textContent = window.i18n.t('lastTrain');
            this.trainTagEl.style.display = 'block';
        } else {
            this.trainTagEl.style.display = 'none';
        }

        // Apply visual styling for departed trains
        if (currentTrain.minutes < currentTime) {
            this.trainTimeEl.classList.add('departed');
        } else {
            this.trainTimeEl.classList.remove('departed');
        }
        this.updateCountdown();
    }

    getAllTrains() {
        const times = this.getCurrentScheduleTimes();

        if (!times || times.length === 0) {
            return [];
        }

        // Convert times to minutes and create train objects
        const trains = times.map(time => {
            const minutes = this.timeToMinutes(time);
            return {
                time: time,
                minutes: minutes,
            };
        });

        return trains;
    }

    getNextTrainIndex() {
        const allTrains = this.getAllTrains();
        const beijingTime = this.getBeijingTime();
        const currentTime = beijingTime.getHours() * 60 + beijingTime.getMinutes();

        // Find first train that hasn't departed yet
        const nextTrainIndex = allTrains.findIndex(train => train.minutes >= currentTime);

        // If no future trains found, default to first train
        return nextTrainIndex >= 0 ? nextTrainIndex : 0;
    }

    getNextTrain() {
        const beijingTime = this.getBeijingTime();
        const currentTime = beijingTime.getHours() * 60 + beijingTime.getMinutes();
        const times = this.getCurrentScheduleTimes();

        if (!times || times.length === 0) {
            return null;
        }

        // Convert times to minutes and find next train
        const timeInMinutes = times.map(time => this.timeToMinutes(time));
        const nextTime = timeInMinutes.find(time => time > currentTime);

        if (!nextTime) {
            return null;
        }

        return {
            time: this.minutesToTime(nextTime),
            minutes: nextTime
        };
    }

    timeToMinutes(timeStr) {
        const [hours, minutes] = timeStr.split(':').map(Number);
        return hours * 60 + minutes;
    }

    minutesToTime(minutes) {
        const hours = Math.floor(minutes / 60);
        const mins = minutes % 60;
        return `${hours.toString().padStart(2, '0')}:${mins.toString().padStart(2, '0')}`;
    }

    startCountdown() {
        this.updateCountdown();
        this.countdownInterval = setInterval(() => {
            this.updateCountdown();
        }, 1000);
    }

    updateCountdown() {
        const allTrains = this.getAllTrains();
        const currentTrain = allTrains[this.currentTrainIndex];

        if (!currentTrain) {
            this.countdownEl.textContent = window.i18n.t('noService');
            return;
        }

        const beijingTime = this.getBeijingTime();
        const currentMinutes = beijingTime.getHours() * 60 + beijingTime.getMinutes();
        const currentSeconds = beijingTime.getSeconds();

        const timeDiff = currentTrain.minutes - currentMinutes;

        if (timeDiff < 0) {
            this.countdownEl.textContent = window.i18n.t('trainDeparted');
            this.countdownEl.classList.add('departed');
            return;
        }

        // Remove departed class for active trains
        this.countdownEl.classList.remove('departed');

        if (timeDiff === 0) {
            // Same minute - show "即将发车"
            this.countdownEl.textContent = window.i18n.t('departing');
        } else {
            const totalSeconds = timeDiff * 60 - currentSeconds;
            const minutes = Math.floor(totalSeconds / 60);
            const seconds = String(totalSeconds % 60);

            if (minutes < 1) {
                // Less than 1 minute - only show seconds
                this.countdownEl.textContent = window.i18n.t('departsInSeconds', { seconds: totalSeconds });
            } else {
                // 1 minute or more - show minutes and seconds
                this.countdownEl.textContent = window.i18n.t('departsIn', { minutes, seconds });
            }
        }
    }

    showError(message) {
        this.loadingEl.style.display = 'none';
        this.appEl.style.display = 'none';
        this.errorEl.style.display = 'block';
        this.errorEl.classList.add('error-state');
        this.errorEl.textContent = message;
    }

    showLocationFallback() {
        this.loadingEl.style.display = 'none';
        this.errorEl.style.display = 'block';
        this.errorEl.classList.remove('error-state');
        this.errorEl.innerHTML = `
            <div>
                <p class="panel-hint">${window.i18n.t('noLocationFallback')}</p>
                <input type="text" id="stationInput" class="station-input"
                       placeholder="${window.i18n.t('searchPlaceholder')}">
                <div id="searchResults" style="max-height: 240px; overflow-y: auto;"></div>
            </div>
        `;

        const input = document.getElementById('stationInput');
        const results = document.getElementById('searchResults');

        input.addEventListener('input', (e) => {
            const query = e.target.value.trim();
            if (!query) {
                results.innerHTML = '';
                return;
            }

            const filtered = this.data.stations.filter(station =>
                station.name.includes(query)
            );

            results.innerHTML = filtered.map(station =>
                `<button class="list-btn" onclick="app.selectStationManually('${station.name}')">
                    ${station.name}
                </button>`
            ).join('');
        });

        input.focus();
    }

    selectStationManually(stationName) {
        this.nearestStation = this.data.stations.find(s => s.name === stationName);
        this.nearestStation.distance = 0; // 手动选择时不显示距离
        this.selectedLine = this.nearestStation.lines[0];
        this.selectedDirection = this.nearestStation.lines[0].directions[0];
        this.currentTrainIndex = this.getNextTrainIndex();

        this.setupUI();
        this.startCountdown();
    }

    showStationSelector() {
        // 如果有用户位置，按距离排序；否则按字母顺序排序
        let sortedStations;
        if (this.userLocation) {
            sortedStations = [...this.data.stations].map(station => {
                const distance = this.calculateDistance(
                    this.userLocation.lat,
                    this.userLocation.lng,
                    station.lat,
                    station.lng
                );
                return { ...station, distance };
            }).sort((a, b) => a.distance - b.distance);
        } else {
            sortedStations = [...this.data.stations].sort((a, b) => a.name.localeCompare(b.name));
        }

        this.errorEl.style.display = 'block';
        this.appEl.style.display = 'none';
        this.errorEl.innerHTML = `
            <div style="text-align: center;">
                <p class="panel-hint">${this.userLocation ? window.i18n.t('nearbyStations') : window.i18n.t('allStations')}</p>
                <div id="stationList" style="max-height: 400px; overflow-y: auto;">
                    ${sortedStations.map(station => `
                        <button class="list-btn" onclick="app.selectStationFromList('${station.name}')">
                            ${station.name}
                        </button>
                    `).join('')}
                </div>
                <button class="back-btn" onclick="app.backToMain()">
                    ${window.i18n.t('back')}
                </button>
            </div>
        `;
    }

    selectStationFromList(stationName) {
        this.nearestStation = this.data.stations.find(s => s.name === stationName);
        // 计算距离（如果有用户位置）
        if (this.userLocation) {
            this.nearestStation.distance = this.calculateDistance(
                this.userLocation.lat,
                this.userLocation.lng,
                this.nearestStation.lat,
                this.nearestStation.lng
            );
        } else {
            this.nearestStation.distance = 0;
        }

        this.selectedLine = this.nearestStation.lines[0];
        this.selectedDirection = this.nearestStation.lines[0].directions[0];
        this.currentTrainIndex = this.getNextTrainIndex();

        this.errorEl.style.display = 'none';
        this.appEl.style.display = 'block';

        this.updateStationDisplay();

        this.renderLineSelector();
        this.renderDirectionSelector();
        this.updateTrainInfo();
        this.startCountdown();
    }

    backToMain() {
        this.errorEl.style.display = 'none';
        this.appEl.style.display = 'block';
    }

    makeStationNameEditable() {
        const currentStationName = this.stationNameEl.textContent;

        // Create input element
        const input = document.createElement('input');
        input.type = 'text';
        input.value = currentStationName;
        input.className = 'station-edit-input';
        input.placeholder = window.i18n.t('searchPlaceholder');

        // Create results container
        const resultsContainer = document.createElement('div');
        resultsContainer.id = 'stationSearchResults';
        resultsContainer.className = 'station-search-results';

        // Store original content
        const originalContent = this.stationNameEl.innerHTML;

        // Replace station name with input
        this.stationNameEl.innerHTML = '';
        this.stationNameEl.appendChild(input);

        // Append results container to body to avoid z-index issues
        document.body.appendChild(resultsContainer);

        // Focus input and select all text
        input.focus();
        input.select();

        // Position results container
        const positionResults = () => {
            const inputRect = input.getBoundingClientRect();
            resultsContainer.style.left = inputRect.left + 'px';
            resultsContainer.style.top = (inputRect.bottom + 5) + 'px';
            resultsContainer.style.width = inputRect.width + 'px';
        };

        // Handle input changes for search suggestions
        input.addEventListener('input', (e) => {
            const query = e.target.value.trim();
            if (!query) {
                resultsContainer.style.display = 'none';
                return;
            }

            const filtered = this.data.stations.filter(station =>
                station.name.includes(query)
            ).slice(0, 8); // Limit to 8 results

            if (filtered.length > 0) {
                resultsContainer.innerHTML = filtered.map(station =>
                    `<div class="search-result-item" onclick="app.selectStationFromInput('${station.name}')">
                        ${station.name}
                    </div>`
                ).join('');
                positionResults();
                resultsContainer.style.display = 'block';
            } else {
                resultsContainer.style.display = 'none';
            }
        });

        // Handle Enter key to search or escape to cancel
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                const query = input.value.trim();
                const exactMatch = this.data.stations.find(station => station.name === query);
                if (exactMatch) {
                    this.selectStationFromInput(exactMatch.name);
                } else {
                    // Find first partial match
                    const partialMatch = this.data.stations.find(station => station.name.includes(query));
                    if (partialMatch) {
                        this.selectStationFromInput(partialMatch.name);
                    }
                }
            } else if (e.key === 'Escape') {
                this.cancelStationEdit(originalContent);
            }
        });

        // Handle click outside to cancel
        const handleClickOutside = (e) => {
            if (!this.stationNameEl.contains(e.target) && !resultsContainer.contains(e.target)) {
                this.cancelStationEdit(originalContent);
                document.removeEventListener('click', handleClickOutside);
            }
        };

        // Add click outside listener after a short delay to avoid immediate trigger
        setTimeout(() => {
            document.addEventListener('click', handleClickOutside);
        }, 100);

        // Store the cleanup function
        this.cleanupStationEdit = () => {
            document.removeEventListener('click', handleClickOutside);
            // Remove results container from body
            if (resultsContainer.parentNode) {
                resultsContainer.parentNode.removeChild(resultsContainer);
            }
        };
    }

    selectStationFromInput(stationName) {
        this.nearestStation = this.data.stations.find(s => s.name === stationName);

        // Calculate distance if user location available
        if (this.userLocation) {
            this.nearestStation.distance = this.calculateDistance(
                this.userLocation.lat,
                this.userLocation.lng,
                this.nearestStation.lat,
                this.nearestStation.lng
            );
        } else {
            this.nearestStation.distance = 0;
        }

        this.selectedLine = this.nearestStation.lines[0];
        this.selectedDirection = this.nearestStation.lines[0].directions[0];
        this.currentTrainIndex = this.getNextTrainIndex();

        // Restore station display
        this.updateStationDisplay();
        this.renderLineSelector();
        this.renderDirectionSelector();
        this.updateTrainInfo();

        // Cleanup event listeners
        if (this.cleanupStationEdit) {
            this.cleanupStationEdit();
            this.cleanupStationEdit = null;
        }
    }

    cancelStationEdit(originalContent) {
        this.stationNameEl.innerHTML = originalContent;

        // Cleanup event listeners
        if (this.cleanupStationEdit) {
            this.cleanupStationEdit();
            this.cleanupStationEdit = null;
        }
    }
}

let app;
document.addEventListener('DOMContentLoaded', () => {
    app = new NextTrainApp();
});