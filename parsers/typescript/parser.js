const fs = require('fs');
const path = require('path');
const ts = require('typescript');

function getLineInfo(sourceFile, position) {
    const { line } = sourceFile.getLineAndCharacterOfPosition(position);
    return line + 1; // Convert to 1-based line number
}

function createChunk(sourceFile, node, moduleName, modulePath, type, name) {
    const startPos = node.pos;
    const endPos = node.end - 1; // Exclusive end

    const startLine = getLineInfo(sourceFile, startPos);
    const endLine = getLineInfo(sourceFile, endPos);

    const content = sourceFile.text.slice(startPos, node.end);

    return {
        id: `${modulePath}.${name}`,
        source: sourceFile.fileName,
        module: modulePath,
        name,
        content,
        start_line: startLine,
        end_line: endLine,
        type,
    };
}

function extractImports(sourceFile, currentFilePath, projectRoot) {
    const imports = [];
    const importNodes = sourceFile.statements.filter(
        (n) => n.kind === ts.SyntaxKind.ImportDeclaration
    );

    importNodes.forEach((node) => {
        const moduleSpecifier = node.moduleSpecifier.text;
        let modulePath = moduleSpecifier
        if (moduleSpecifier.startsWith('.')) {
            const currentFileDir = path.dirname(currentFilePath);
            const absolutePath = path.resolve(currentFileDir, moduleSpecifier);
            const relativePath = path.relative(projectRoot, absolutePath);

            // Process the relative path to get module path
            const parts = moduleSpecifier.startsWith('.') ? relativePath.split(path.sep) : [moduleSpecifier];
            const lastPart = parts.pop();
            const fileName = path.parse(lastPart).name; // Remove extension
            parts.push(fileName);
            const adjustedPath = parts.join(path.sep);
            modulePath = adjustedPath.split(path.sep).join('.');
        }

        // Handle different import types
        if (node.importClause?.name) {
            const name = node.importClause.name.text;
            imports.push({
                name: name,
                module: modulePath,
                type: 'default',
            });
        }

        if (node.importClause?.namedBindings) {
            const namedImports = node.importClause.namedBindings.elements.map((element) => ({
                name: element.name.text,
                as: element.propertyName?.text || element.name.text,
            }));

            namedImports.forEach((imp) => {
                imports.push({
                    name: imp.as,
                    originalName: imp.name,
                    module: modulePath,
                    type: 'named',
                });
            });
        }

        if (ts.isImportDeclaration(node) && node.importClause?.name) {
            const name = node.importClause.name.text;
            imports.push({
                name: name,
                module: modulePath,
                type: 'namespace',
            });
        }
    });

    return imports;
}

function parseFile(filePath, projectRoot) {
    const fileContent = fs.readFileSync(filePath, 'utf-8');
    const sourceFile = ts.createSourceFile(
        filePath,
        fileContent,
        ts.ScriptTarget.Latest,
        true
    );

    const moduleName = path.basename(filePath, path.extname(filePath));
    const currentDir = path.dirname(filePath);
    const modulePath = path
        .relative(projectRoot, currentDir)
        .split(path.sep)
        .join('.') + '.' + moduleName;

    const chunks = [];
    const dependencies = [];
    const imports = extractImports(sourceFile, filePath, projectRoot);

    // File chunk
    const totalLines = sourceFile.getLineStarts().length;
    chunks.push({
        id: modulePath,
        source: filePath,
        module: modulePath,
        name: null,
        content: fileContent,
        start_line: 1,
        end_line: totalLines,
        type: 'file',
    });

    // Process imports chunk
    const importsNodes = sourceFile.statements.filter(
        (n) => n.kind === ts.SyntaxKind.ImportDeclaration
    );
    if (importsNodes.length > 0) {
        const importCode = importsNodes
            .map((n) => sourceFile.text.slice(n.pos, n.end))
            .join('\n');
        const startLine = getLineInfo(sourceFile, importsNodes[0].pos);
        const endLine = getLineInfo(
            sourceFile,
            importsNodes[importsNodes.length - 1].end
        );
        chunks.push({
            id: `${modulePath}._imports_`,
            source: filePath,
            module: modulePath,
            name: '_imports_',
            content: importCode,
            start_line: startLine,
            end_line: endLine,
            type: 'imports',
        });
    }

    // Process declarations
    const declarations = sourceFile.statements.filter(
        (n) => n.kind !== ts.SyntaxKind.ImportDeclaration
    );

    const declarationChunks = [];
    declarations.forEach((node) => {
        let name, type;
        switch (node.kind) {
            case ts.SyntaxKind.FunctionDeclaration:
                name = node.name?.text || `line${getLineInfo(sourceFile, node.pos)}`;
                type = 'function';
                break;
            case ts.SyntaxKind.ClassDeclaration:
                name = node.name?.text || `line${getLineInfo(sourceFile, node.pos)}`;
                type = 'class';
                break;
            case ts.SyntaxKind.VariableStatement:
                const varDecl = node.declarationList.declarations[0];
                name = varDecl.name.getText() || `line${getLineInfo(sourceFile, node.pos)}`;
                type = 'variable';
                break;
            default:
                name = `line${getLineInfo(sourceFile, node.pos)}`;
                type = 'other';
                break;
        }

        const chunk = createChunk(
            sourceFile,
            node,
            moduleName,
            modulePath,
            type,
            name
        );
        declarationChunks.push(chunk);
    });

    chunks.push(...declarationChunks);

    // Create dependencies
    const nameToChunk = new Map();
    declarationChunks.forEach((c) => nameToChunk.set(c.name, c));

    // Dependency to imports chunk
    const importChunkId = `${modulePath}._imports_`;
    chunks.forEach((chunk) => {
        if (chunk.type !== 'imports' && chunk.type !== 'file') {
            dependencies.push({
                snippet_id: chunk.id,
                dependency_name: importChunkId,
            });
        }
    });

    // Internal dependencies
    declarationChunks.forEach((currentChunk) => {
        const contentAST = ts.createSourceFile(
            'temp.ts',
            currentChunk.content,
            ts.ScriptTarget.Latest,
            true
        );

        const identifiers = new Set();

        function collectIdentifiers(node) {
            if (ts.isIdentifier(node)) {
                identifiers.add(node.text);
            }
            ts.forEachChild(node, collectIdentifiers);
        }

        collectIdentifiers(contentAST);

        // Local dependencies
        identifiers.forEach((refName) => {
            const refChunk = nameToChunk.get(refName);
            if (refChunk && refChunk.id !== currentChunk.id) {
                dependencies.push({
                    snippet_id: currentChunk.id,
                    dependency_name: refChunk.id,
                });
            }
        });

        // Imported dependencies
        imports.forEach((imp) => {
            if (identifiers.has(imp.name)) {
                let depName;
                if (imp.type === 'named') {
                    depName = `${imp.module}.${imp.originalName}`;
                } else {
                    depName = `${imp.module}.${imp.name}`;
                }
                dependencies.push({
                    snippet_id: currentChunk.id,
                    dependency_name: depName,
                });
            }
        });
    });

    // Remove duplicates
    const uniqueDeps = Array.from(
        new Set(dependencies.map(JSON.stringify))
    ).map(JSON.parse);

    return {
        chunks: chunks.map((c) => ({
            ...c,
            content: c.content.replace(/\r?\n/g, '\n'), // Escape newlines
        })),
        dependencies: uniqueDeps,
    };
}

// CLI entry point
if (require.main === module) {
    const filePath = process.argv[2];
    const projectRoot = process.argv[3];
    if (!filePath || !projectRoot) {
        console.error('Usage: node parser.js <file.js> <project_root>');
        process.exit(1);
    }

    const result = parseFile(filePath, projectRoot);
    console.log(JSON.stringify(result, null, 2));
}