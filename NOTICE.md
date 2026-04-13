## Template / third-party code in `nutonic/`

The `nutonic/` Gradle project was partly inspired by the **Compose Multiplatform “Image Viewer” example** from JetBrains: same module layout (`androidApp`, `shared`, `webApp`, `desktopApp`, `mapview-desktop`); Gradle root name, Kotlin packages, and Android identifiers have been modified (see `nutonic/settings.gradle.kts`, `nutonic/androidApp/build.gradle.kts`, and sources under `nutonic/shared/`).

Upstream source lives in the JetBrains **compose-multiplatform** repository, under **`examples/imageviewer`**:  
https://github.com/JetBrains/compose-multiplatform/tree/master/examples/imageviewer  

That repository is licensed under the **Apache License, Version 2.0**:  
https://github.com/JetBrains/compose-multiplatform/blob/master/LICENSE.txt  

it is cited as an inspiration , not as the final Nutonic product implementation.

## Map asset

[dummy_map.jpg](./nutonic/shared/src/commonMain/composeResources/drawable/dummy_map.jpg) is available under the Open Database License: https://www.openstreetmap.org/copyright
